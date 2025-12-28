from flask import Flask, render_template, jsonify, request, send_from_directory
import os
import threading
from threading import Lock

from config import QUERY_DICT, REFERENCE_ISSUE_NUMBER
from utils import convert_to_serializable, build_query_from_list
from data_access import (
    load_issue_date_mapping,
    load_summary_data,
    load_trend_data,
    save_analysis_to_csv
)
from analysis import (
    run_analysis,
    get_analysis_results,
    get_analysis_progress,
    reset_analysis_progress
)

app = Flask(__name__)

# グローバル変数
analysis_lock = Lock()

@app.route('/')
def index():
    """トップページ"""
    return render_template('index.html')

@app.route('/data')
def data_viewer():
    """CSVデータビューアページ"""
    return render_template('data_viewer.html')

@app.route('/api/get_summary_data')
def get_summary_data():
    """保存されたサマリーデータを取得"""
    try:
        df = load_summary_data()
        
        # DataFrameをJSON形式に変換
        data = df.to_dict('records')
        
        # NumPy/Pandasのデータ型を変換
        serializable_data = []
        for row in data:
            serializable_row = {k: convert_to_serializable(v) for k, v in row.items()}
            serializable_data.append(serializable_row)
        
        return jsonify({
            "data": serializable_data,
            "columns": list(df.columns)
        })
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error loading CSV data: {error_detail}")
        return jsonify({"error": f"データの読み込みに失敗しました: {str(e)}"}), 500

@app.route('/api/get_trend_data')
def get_trend_data():
    """保存されたトレンドデータを取得"""
    try:
        df = load_trend_data()
        
        # DataFrameをJSON形式に変換
        data = df.to_dict('records')
        
        # NumPy/Pandasのデータ型を変換
        serializable_data = []
        for row in data:
            serializable_row = {k: convert_to_serializable(v) for k, v in row.items()}
            serializable_data.append(serializable_row)
        
        return jsonify({
            "data": serializable_data,
            "columns": list(df.columns)
        })
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error loading trend CSV data: {error_detail}")
        return jsonify({"error": f"トレンドデータの読み込みに失敗しました: {str(e)}"}), 500

@app.route('/api/get_queries')
def get_queries():
    """デフォルトのクエリ辞書と基準号数を取得"""
    # クエリリストを文字列に変換
    queries = []
    for k, v in QUERY_DICT.items():
        if isinstance(v, list):
            query_string = build_query_from_list(v)
            queries.append({'name': k, 'query': query_string, 'query_list': v})
        else:
            # 後方互換性のため、文字列の場合もサポート
            queries.append({'name': k, 'query': v, 'query_list': [v]})
    
    mapping = load_issue_date_mapping()
    
    # タイムゾーン情報を除いて文字列に変換
    date_mapping_str = {}
    for k, v in mapping.items():
        if hasattr(v, 'tz_localize'):
            # タイムゾーン情報を削除
            date_mapping_str[k] = v.tz_localize(None).strftime('%Y-%m-%d %H:%M:%S')
        else:
            date_mapping_str[k] = v.strftime('%Y-%m-%d %H:%M:%S')
    
    return jsonify({
        "queries": queries,
        "reference_issue_number": REFERENCE_ISSUE_NUMBER,
        "issue_date_mapping": date_mapping_str
    })
def start_analysis():
    """解析を開始"""
    global analysis_results, analysis_progress
    
    with analysis_lock:
        if analysis_progress["status"] == "running":
            return jsonify({"error": "Analysis already running"}), 400
        
        analysis_progress = {"current": 0, "total": 0, "status": "running", "message": "初期化中..."}
        analysis_results = None
    
    # リクエストからクエリと基準号数を取得
    data = request.get_json()
    queries = data.get('queries', [])
    reference_issue_number = data.get('reference_issue_number', REFERENCE_ISSUE_NUMBER)
    trend_words_data = data.get('trend_words', [])  # トレンドワード情報
    original_queries = data.get('original_queries', {})  # 元のクエリ情報
    
    # クエリが空の場合はデフォルトを使用
    if not queries:
        queries = [{'name': k, 'query': v} for k, v in QUERY_DICT.items()]
    
    # 別スレッドで解析を実行
    import threading
    thread = threading.Thread(target=run_analysis, args=(queries, reference_issue_number, trend_words_data, original_queries))
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Analysis started"})

def run_analysis(queries, reference_issue_number=None, trend_words_data=None, original_queries=None):
    """解析を実行(バックグラウンド)"""
    global analysis_results, analysis_progress
    
    try:
        # クエリをリストから辞書に変換し、isTrendフラグも保持
        query_dict = {q['name']: q['query'] for q in queries}
        trend_flags = {q['name']: q.get('isTrend', False) for q in queries}

        interval_hour = INTERVAL_HOUR
        span_hour = SPAN_HOUR
        # 号数から日付を取得
        if reference_issue_number is None:
            reference_issue_number = REFERENCE_ISSUE_NUMBER
        reference_base_datetime = get_date_from_issue_number(reference_issue_number)
        
        if reference_base_datetime is None:
            raise ValueError(f"号数 {reference_issue_number} に対応する日付が見つかりません")

        # トレンドワードマップを作成（作品名 -> トレンドワードリスト）
        trend_map = {}
        if trend_words_data:
            for trend in trend_words_data:
                work_name = trend.get('workName')
                trend_word = trend.get('word', '').strip()
                if work_name and trend_word:
                    if work_name not in trend_map:
                        trend_map[work_name] = []
                    trend_map[work_name].append(trend_word)
        
        # 元のクエリ情報がない場合は空の辞書
        if original_queries is None:
            original_queries = {}

        # 処理対象を計算
        total_tasks = 0
        for display_name in query_dict.keys():
            if trend_flags.get(display_name, False):
                # トレンド専用クエリは1回のみ
                total_tasks += 1
            else:
                # 通常作品
                trends = trend_map.get(display_name, [])
                original_query_elements = original_queries.get(display_name, [query_dict[display_name]])
                new_trends = [t for t in trends if t not in original_query_elements]
                
                if trends:
                    if new_trends:
                        # トレンドワードが元のクエリに含まれていない場合: 元のクエリ + トレンド付き + 個別取得
                        total_tasks += 2 + len(trends)
                    else:
                        # トレンドワードが元のクエリに含まれている場合: 作品データ1回 + 個別取得
                        total_tasks += 1 + len(trends)
                else:
                    # トレンドワードがない場合は1回
                    total_tasks += 1
        
        analysis_progress["total"] = total_tasks
        summary_data = []
        current_task = 0

        for display_name, query_string in query_dict.items():
            is_trend_query = trend_flags.get(display_name, False)
            
            if is_trend_query:
                # トレンド専用クエリはそのまま1回解析
                current_task += 1
                analysis_progress["current"] = current_task
                analysis_progress["message"] = f"処理中: {display_name}"
                
                result = analyze_word(display_name, query_string, interval_hour, span_hour, reference_base_datetime)
                result['isTrend'] = True
                summary_data.append(result)
            else:
                # 通常の作品クエリ
                trends = trend_map.get(display_name, [])
                original_query_elements = original_queries.get(display_name, [query_dict[display_name]])
                
                # トレンドワードが元のクエリに含まれているかチェック
                new_trends = [t for t in trends if t not in original_query_elements]
                
                if trends:
                    # トレンドワードがある場合（元クエリに含まれているかどうかに関わらず）
                    if new_trends:
                        # 1. 元のクエリのみで解析（トレンドワードが元クエリに含まれていない場合）
                        current_task += 1
                        analysis_progress["current"] = current_task
                        analysis_progress["message"] = f"処理中: {display_name} (元のクエリ)"
                        
                        original_query_string = build_query_from_list(original_query_elements)
                        result_original = analyze_word(display_name, original_query_string, interval_hour, span_hour, reference_base_datetime)
                        result_original['isTrend'] = False
                        result_original['withTrendWord'] = False
                        result_original['trendWords'] = []
                        summary_data.append(result_original)
                        
                        # 2. トレンドワード付きで解析
                        current_task += 1
                        analysis_progress["current"] = current_task
                        analysis_progress["message"] = f"処理中: {display_name} (トレンド付き)"
                        
                        result_with_trend = analyze_word(display_name, query_string, interval_hour, span_hour, reference_base_datetime)
                        result_with_trend['isTrend'] = False
                        result_with_trend['withTrendWord'] = True
                        result_with_trend['trendWords'] = new_trends
                        summary_data.append(result_with_trend)
                    else:
                        # トレンドワードが元のクエリに含まれている場合は、作品データは1回のみ
                        current_task += 1
                        analysis_progress["current"] = current_task
                        analysis_progress["message"] = f"処理中: {display_name}"
                        
                        result = analyze_word(display_name, query_string, interval_hour, span_hour, reference_base_datetime)
                        result['isTrend'] = False
                        result['withTrendWord'] = True  # トレンド含むとしてマーク
                        result['trendWords'] = trends  # 全トレンドワードを記録
                        summary_data.append(result)
                    
                    # 3. トレンドワード個別の解析（元クエリに含まれているかどうかに関わらず）
                    for trend_word in trends:
                        current_task += 1
                        analysis_progress["current"] = current_task
                        analysis_progress["message"] = f"処理中: {display_name} ({trend_word})"
                        
                        # トレンドワード単体でクエリを構築
                        trend_single_query = build_query_from_list([trend_word])
                        result_trend_single = analyze_word(display_name, trend_single_query, interval_hour, span_hour, reference_base_datetime)
                        result_trend_single['isTrend'] = False
                        result_trend_single['withTrendWord'] = True
                        result_trend_single['trendWords'] = [trend_word]
                        result_trend_single['isTrendIndividual'] = True  # 個別取得フラグ
                        summary_data.append(result_trend_single)
                else:
                    # トレンドワードがない場合は1回のみ
                    current_task += 1
                    analysis_progress["current"] = current_task
                    analysis_progress["message"] = f"処理中: {display_name}"
                    
                    result = analyze_word(display_name, query_string, interval_hour, span_hour, reference_base_datetime)
                    result['isTrend'] = False
                    result['withTrendWord'] = False
                    result['trendWords'] = []
                    summary_data.append(result)

        analysis_results = summary_data
        analysis_progress["status"] = "completed"
        analysis_progress["message"] = "解析完了"
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error in run_analysis: {error_detail}")
        analysis_progress["status"] = "error"
        analysis_progress["message"] = f"エラー: {str(e)}"

@app.route('/api/progress')
def get_progress():
    """解析の進捗を取得"""
    return jsonify(analysis_progress)

@app.route('/api/results')
def get_results():
    """解析結果を取得"""
    if analysis_results is None:
        return jsonify({"error": "No results available"}), 404
    
    # NumPy/Pandasのデータ型をJSON serializable な型に変換
    serializable_results = []
    for result in analysis_results:
        serializable_result = {k: convert_to_serializable(v) for k, v in result.items()}
        serializable_results.append(serializable_result)
    
    return jsonify({"results": serializable_results})

@app.route('/api/save_to_csv', methods=['POST'])
def save_to_csv():
    """解析結果をCSVデータベースファイルに保存・更新"""
    if analysis_results is None:
        return jsonify({"error": "No results available"}), 404
    
    try:
        # リクエストから号数とトレンドワード情報を取得
        data = request.get_json()
        issue_number = data.get('issue_number', REFERENCE_ISSUE_NUMBER)
        trend_words_data = data.get('trend_words', [])  # [{word, workName, rank}, ...]
        
        # === 作品データの保存 ===
        csv_filename = 'yahoo_word_analysis_summary.csv'
        
        # 新しいデータを準備
        new_rows = []
        for result in analysis_results:
            # isTrendがTrueまたはisTrendIndividualがTrueの場合はスキップ（作品データには含めない）
            if result.get('isTrend', False) or result.get('isTrendIndividual', False):
                continue
            
            # トレンドワード付きバージョンかどうかを判定
            work_name = result['作品名']
            has_trend = result.get('withTrendWord', False)
                
            new_row = {
                '号数': issue_number,
                '作品名': work_name,
                'トレンド含む': has_trend,  # True/False
                'クエリ': result['クエリ'],
                '参照': result['参照カウント'] if result['参照カウント'] is not None else 0,
                '1時間': result['1時間集計'] if result['1時間集計'] is not None else 0,
                '全体': result['全体集計'] if result['全体集計'] is not None else 0,
                '終了': result['全体集計終了時刻']
            }
            new_rows.append(new_row)
        
        df_new = pd.DataFrame(new_rows)
        
        # 既存のCSVファイルを読み込み、なければ新規作成
        if os.path.exists(csv_filename) and os.path.getsize(csv_filename) > 0:
            try:
                df_existing = pd.read_csv(csv_filename, encoding='utf-8-sig')
                # 同じ号数、作品名、トレンド含むの組み合わせがあれば削除（更新）
                if len(df_new) > 0 and '作品名' in df_existing.columns:
                    # トレンド含むカラムがない場合は追加
                    if 'トレンド含む' not in df_existing.columns:
                        df_existing['トレンド含む'] = False
                    
                    # 複合キーで削除
                    keys_to_remove = df_new[['号数', '作品名', 'トレンド含む']].apply(tuple, axis=1).tolist()
                    df_existing = df_existing[
                        ~df_existing[['号数', '作品名', 'トレンド含む']].apply(tuple, axis=1).isin(keys_to_remove)
                    ]
            except Exception as e:
                print(f"Warning: Could not read existing CSV, creating new one: {e}")
                df_existing = pd.DataFrame(columns=['号数', '作品名', 'トレンド含む', 'クエリ', '参照', '1時間', '全体', '終了'])
        else:
            df_existing = pd.DataFrame(columns=['号数', '作品名', 'トレンド含む', 'クエリ', '参照', '1時間', '全体', '終了'])
        
        # 新しいデータを追加
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        
        # 号数、作品名、トレンド含む（False→True順）でソート
        df_combined = df_combined.sort_values(by=['号数', '作品名', 'トレンド含む'], ascending=[True, True, True])
        
        # CSVに保存
        df_combined.to_csv(csv_filename, index=False, encoding='utf-8-sig')
        
        # === トレンドワードデータの保存 ===
        trend_csv_filename = 'yahoo_trend_analysis_summary.csv'
        trend_saved_count = 0
        
        if trend_words_data:
            # トレンドワードのランク情報を作成（作品名 -> {word, rank}）
            trend_rank_map = {}
            for t in trend_words_data:
                if t.get('word', '').strip() and t.get('workName', '').strip():
                    work_name = t['workName']
                    if work_name not in trend_rank_map:
                        trend_rank_map[work_name] = []
                    trend_rank_map[work_name].append({'word': t['word'], 'rank': t.get('rank', '')})
            
            # トレンドワードの新しいデータを準備
            trend_new_rows = []
            
            # トレンドワード個別取得の結果を保存（isTrendIndividual=Trueの結果から）
            for result in analysis_results:
                if result.get('isTrendIndividual', False):
                    work_name = result['作品名']
                    trend_words_list = result.get('trendWords', [])
                    
                    if not trend_words_list or len(trend_words_list) != 1:
                        continue
                    
                    trend_word = trend_words_list[0]
                    
                    # 対応するランク情報を取得
                    rank_info_list = trend_rank_map.get(work_name, [])
                    rank = ''
                    for info in rank_info_list:
                        if info['word'] == trend_word:
                            rank = info['rank']
                            break
                    
                    trend_new_row = {
                        '号数': issue_number,
                        '作品名': work_name,
                        'トレンドワード': trend_word,
                        '順位': rank,
                        '参照': result['参照カウント'] if result['参照カウント'] is not None else 0,
                        '1時間': result['1時間集計'] if result['1時間集計'] is not None else 0,
                        '全体': result['全体集計'] if result['全体集計'] is not None else 0,
                        '終了': result['全体集計終了時刻']
                    }
                    trend_new_rows.append(trend_new_row)
            
            if trend_new_rows:
                df_trend_new = pd.DataFrame(trend_new_rows)
                
                # 既存のトレンドCSVファイルを読み込み、なければ新規作成
                if os.path.exists(trend_csv_filename) and os.path.getsize(trend_csv_filename) > 0:
                    try:
                        df_trend_existing = pd.read_csv(trend_csv_filename, encoding='utf-8-sig')
                        # 同じ号数と作品名の組み合わせがあれば削除（更新）
                        if '作品名' in df_trend_existing.columns:
                            keys_to_remove = df_trend_new[['号数', '作品名']].apply(tuple, axis=1).tolist()
                            df_trend_existing = df_trend_existing[
                                ~df_trend_existing[['号数', '作品名']].apply(tuple, axis=1).isin(keys_to_remove)
                            ]
                    except Exception as e:
                        print(f"Warning: Could not read existing trend CSV, creating new one: {e}")
                        df_trend_existing = pd.DataFrame(columns=['号数', '作品名', 'トレンドワード', '順位', '参照', '1時間', '全体', '終了'])
                else:
                    df_trend_existing = pd.DataFrame(columns=['号数', '作品名', 'トレンドワード', '順位', '参照', '1時間', '全体', '終了'])
                
                # 新しいデータを追加
                df_trend_combined = pd.concat([df_trend_existing, df_trend_new], ignore_index=True)
                
                # 号数、作品名でソート
                df_trend_combined = df_trend_combined.sort_values(by=['号数', '作品名'], ascending=[True, True])
                
                # CSVに保存
                df_trend_combined.to_csv(trend_csv_filename, index=False, encoding='utf-8-sig')
                trend_saved_count = len(trend_new_rows)
        
        message = f"データを保存しました (作品: {len(new_rows)}件"
        if trend_saved_count > 0:
            message += f", トレンド: {trend_saved_count}件"
        message += ")"
        
        return jsonify({
            "message": message,
            "issue_number": issue_number,
            "saved_count": len(new_rows),
            "trend_saved_count": trend_saved_count
        })
        
    except Exception as e:
        import traceback
        error_detail = traceback.format_exc()
        print(f"Error saving to CSV: {error_detail}")
        return jsonify({"error": f"CSV保存エラー: {str(e)}"}), 500

@app.route('/static/images/<path:filename>')
def serve_image(filename):
    """画像ファイルを提供する"""
    images_dir = os.path.join(os.path.dirname(__file__), 'images')
    return send_from_directory(images_dir, filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
