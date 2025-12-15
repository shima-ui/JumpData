from flask import Flask, render_template, jsonify, send_file, request, send_from_directory
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import numpy as np
import io
import os
from threading import Lock
from config import QUERY_DICT, INTERVAL_HOUR, SPAN_HOUR, REFERENCE_ISSUE_NUMBER

app = Flask(__name__)

# グローバル変数
analysis_lock = Lock()
analysis_results = None
analysis_progress = {"current": 0, "total": 0, "status": "idle", "message": ""}
issue_date_mapping_cache = None  # 号数-日付マッピングのキャッシュ

# 号数-日付マッピングを読み込む関数
def load_issue_date_mapping():
    """issue_date_mapping.csvから号数と日付のマッピングを読み込む"""
    global issue_date_mapping_cache
    
    if issue_date_mapping_cache is not None:
        return issue_date_mapping_cache
    
    try:
        df = pd.read_csv('issue_date_mapping.csv')
        mapping = {}
        for _, row in df.iterrows():
            issue_num = int(row['issue_number'])
            date_str = row['date']
            # タイムゾーン情報を付与
            dt = pd.to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.tz_localize('Asia/Tokyo')
            mapping[issue_num] = dt
        issue_date_mapping_cache = mapping
        return mapping
    except Exception as e:
        print(f"Error loading issue_date_mapping.csv: {str(e)}")
        import traceback
        traceback.print_exc()
        return {}

def get_date_from_issue_number(issue_number):
    """号数から日付を取得"""
    mapping = load_issue_date_mapping()
    return mapping.get(int(issue_number))

# --- YahooGateway クラスの定義 ---
Headers = {"User-Agent": "Mozilla/5.0"}
CRUMB_COUNT = 0
CRUMB_REUSE_COUNT = 20
CRUMB = None

class YahooGateway():
    def _get_crumb_token(self) -> str:
        """Yahooリアルタイム検索のクラムトークンを取得する。"""
        try:
            global CRUMB, CRUMB_COUNT
            if CRUMB_COUNT >= CRUMB_REUSE_COUNT or CRUMB is None:
                session = requests.Session()
                response = session.get("https://search.yahoo.co.jp/realtime/search?p=x.com", headers=Headers)
                response.raise_for_status()
                crumb_match = re.search(r'"crumb"\s*:\s*"([^"]+)"', response.text)
                CRUMB = crumb_match.group(1) if crumb_match else None
                CRUMB_COUNT = 0
            else:
                CRUMB_COUNT += 1
            return CRUMB
        except Exception as e:
            print(f"Error fetching Yahoo crumb token: {str(e)}")

    def get_yahoo_word_counts(self, word: str, interval_hour: int = 24, span_hour: int = 30 * 24) -> list[dict]:
        """Yahooリアルタイム検索で指定されたワードのポスト数を取得する。"""
        try:
            crumb = self._get_crumb_token()
            params = {
                "crumb": crumb,
                "p": word,
                "interval": int(interval_hour * 60 * 60),
                "span": span_hour * 60 * 60,
            }
            session = requests.Session()
            response = session.get("https://search.yahoo.co.jp/realtime/api/v1/transition", params=params)
            response.raise_for_status()

            yahoo_dict = []
            for entry in response.json().get("tweetTransition", {}).get("entry", []):
                from_dt = datetime.fromtimestamp(entry.get("from"), tz=ZoneInfo("Asia/Tokyo"))
                to_dt = datetime.fromtimestamp(entry.get("to"), tz=ZoneInfo("Asia/Tokyo"))
                count = entry.get("count")
                yahoo_dict.append(
                    {
                        "word": word,
                        "from_date": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "to_date": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        "count": count,
                    }
                )
            yahoo_dict_list = yahoo_dict.copy()
            return yahoo_dict_list
        except Exception as e:
            print(f"Error fetching Yahoo word counts for '{word}': {str(e)}")
            return []

def convert_to_serializable(obj):
    """NumPy/Pandasのデータ型をJSON serializable な型に変換"""
    # リストや辞書は再帰的に処理
    if isinstance(obj, list):
        return [convert_to_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: convert_to_serializable(v) for k, v in obj.items()}
    # NumPy/Pandasの型変換
    elif isinstance(obj, (np.integer, np.int64, np.int32)):
        return int(obj)
    elif isinstance(obj, (np.floating, np.float64, np.float32)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    # スカラー値のみpd.isna()でチェック
    elif isinstance(obj, (int, float, str, type(None))):
        return obj
    else:
        # その他の型（Noneやpd.NA等）
        try:
            if pd.isna(obj):
                return None
        except (ValueError, TypeError):
            pass
        return obj

def analyze_word(display_name, query_string, interval_hour, span_hour, reference_base_datetime):
    """単一のワードを解析"""
    yahoo_gateway = YahooGateway()
    
    yahoo_word_counts = yahoo_gateway.get_yahoo_word_counts(query_string, interval_hour, span_hour)

    if not yahoo_word_counts:
        return {
            '作品名': display_name,
            'クエリ': query_string,
            '参照カウント': None,
            '1時間集計': None,
            '全体集計': None,
            '全体集計終了時刻': 'データなし',
            'plot': None
        }

    df_yahoo_word_counts = pd.DataFrame(yahoo_word_counts)
    df_yahoo_word_counts['from_date'] = pd.to_datetime(df_yahoo_word_counts['from_date'])
    
    # タイムゾーンを統一（Asia/Tokyo）
    if df_yahoo_word_counts['from_date'].dt.tz is None:
        df_yahoo_word_counts['from_date'] = df_yahoo_word_counts['from_date'].dt.tz_localize('Asia/Tokyo')
    
    # reference_base_datetimeがタイムゾーン情報を持っているか確認
    if hasattr(reference_base_datetime, 'tzinfo') and reference_base_datetime.tzinfo is None:
        reference_base_datetime = reference_base_datetime.tz_localize('Asia/Tokyo')

    # 1時間前から15分おきに4つのデータポイントを取得
    reference_times = [
        reference_base_datetime - timedelta(minutes=60),  # 1時間前
        reference_base_datetime - timedelta(minutes=45),  # 45分前
        reference_base_datetime - timedelta(minutes=30),  # 30分前
        reference_base_datetime - timedelta(minutes=15),  # 15分前
    ]
    
    reference_counts = []
    for ref_time in reference_times:
        ref_row = df_yahoo_word_counts[df_yahoo_word_counts['from_date'] == ref_time]
        if not ref_row.empty:
            reference_counts.append(ref_row['count'].iloc[0])
    
    if reference_counts:
        reference_count = np.mean(reference_counts)
    else:
        reference_count = 0

    df_sum_calculation = df_yahoo_word_counts[df_yahoo_word_counts['from_date'] >= reference_base_datetime].copy()
    min_sum_duration_end_time = reference_base_datetime + timedelta(hours=1)
    actual_sum_end_datetime = None

    if not df_sum_calculation.empty:
        natural_end_candidates = df_sum_calculation[df_sum_calculation['count'] <= reference_count]

        if not natural_end_candidates.empty:
            natural_sum_end_datetime = natural_end_candidates['from_date'].min()
        else:
            natural_sum_end_datetime = None

        if natural_sum_end_datetime is None:
            actual_sum_end_datetime = df_sum_calculation['from_date'].max() + timedelta(minutes=int(interval_hour * 60))
        elif natural_sum_end_datetime < min_sum_duration_end_time:
            df_after_min_duration = df_sum_calculation[df_sum_calculation['from_date'] >= min_sum_duration_end_time]

            if not df_after_min_duration.empty:
                re_drop_candidates = df_after_min_duration[df_after_min_duration['count'] <= reference_count]
                if not re_drop_candidates.empty:
                    actual_sum_end_datetime = re_drop_candidates['from_date'].min()
                else:
                    actual_sum_end_datetime = df_sum_calculation['from_date'].max() + timedelta(minutes=int(interval_hour * 60))
            else:
                actual_sum_end_datetime = df_sum_calculation['from_date'].max() + timedelta(minutes=int(interval_hour * 60))
        else:
            actual_sum_end_datetime = natural_sum_end_datetime
    else:
        actual_sum_end_datetime = None

    # 1時間集計の範囲
    df_one_hour_range = df_sum_calculation[df_sum_calculation['from_date'] < min_sum_duration_end_time].copy()
    one_hour_sum_value = df_one_hour_range['count'].sum() if not df_one_hour_range.empty else 0
    
    # 参照値を下回るまでの集計範囲（現行）
    if actual_sum_end_datetime:
        df_sum_range = df_sum_calculation[df_sum_calculation['from_date'] < actual_sum_end_datetime].copy()
    else:
        df_sum_range = pd.DataFrame()

    sum_value = df_sum_range['count'].sum() if not df_sum_range.empty else 0
    
    # 1時間以降の集計範囲（1時間～参照値を下回るまで）
    if actual_sum_end_datetime and actual_sum_end_datetime > min_sum_duration_end_time:
        df_after_one_hour_range = df_sum_calculation[
            (df_sum_calculation['from_date'] >= min_sum_duration_end_time) & 
            (df_sum_calculation['from_date'] < actual_sum_end_datetime)
        ].copy()
    else:
        df_after_one_hour_range = pd.DataFrame()
    
    print(f"分析完了: {display_name}", flush=True)
    print(f"基準日時: {reference_base_datetime}", flush=True)
    print(f"参照カウント: {reference_count}", flush=True)
    
    # タイムゾーン情報を除去して文字列化する関数
    def format_datetime(dt):
        if hasattr(dt, 'tz_localize'):
            return dt.tz_localize(None).strftime('%Y-%m-%d %H:%M:%S')
        elif hasattr(dt, 'strftime'):
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            return str(dt)
    
    # グラフ用の生データを準備
    chart_data = []
    for _, row in df_yahoo_word_counts.iterrows():
        chart_data.append({
            'x': format_datetime(row['from_date']),
            'y': int(row['count'])
        })
    
    # 1時間集計範囲のデータ（0〜1時間）
    one_hour_range_data = []
    if not df_one_hour_range.empty:
        for _, row in df_one_hour_range.iterrows():
            if row['count'] > reference_count:
                one_hour_range_data.append({
                    'x': format_datetime(row['from_date']),
                    'y': int(row['count'])
                })
    
    # 1時間以降の集計範囲のデータ（1時間〜参照値を下回るまで）
    after_one_hour_range_data = []
    if not df_after_one_hour_range.empty:
        for _, row in df_after_one_hour_range.iterrows():
            if row['count'] > reference_count:
                after_one_hour_range_data.append({
                    'x': format_datetime(row['from_date']),
                    'y': int(row['count'])
                })

    # 参照時刻として基準時刻の15分前を使用（グラフ表示用）
    reference_datetime_for_display = reference_base_datetime - timedelta(minutes=15)
    
    return {
        '作品名': display_name,
        'クエリ': query_string,
        '参照カウント': reference_count,
        '1時間集計': one_hour_sum_value,
        '全体集計': sum_value,
        '全体集計終了時刻': format_datetime(actual_sum_end_datetime) if actual_sum_end_datetime else 'データなし',
        'chart_data': chart_data,
        'one_hour_range_data': one_hour_range_data,
        'after_one_hour_range_data': after_one_hour_range_data,
        'reference_datetime': format_datetime(reference_datetime_for_display),
        'reference_base_datetime': format_datetime(reference_base_datetime)
    }

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
        csv_filename = 'yahoo_word_analysis_summary.csv'
        if not os.path.exists(csv_filename):
            return jsonify({"error": "データファイルが見つかりません"}), 404
        
        df = pd.read_csv(csv_filename, encoding='utf-8-sig')
        
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
        print(f"Error loading CSV data: {error_detail}")
        return jsonify({"error": f"データの読み込みに失敗しました: {str(e)}"}), 500

@app.route('/api/get_trend_data')
def get_trend_data():
    """保存されたトレンドデータを取得"""
    try:
        csv_filename = 'yahoo_trend_analysis_summary.csv'
        if not os.path.exists(csv_filename):
            return jsonify({"data": [], "columns": []})
        
        df = pd.read_csv(csv_filename, encoding='utf-8-sig')
        
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

def build_query_from_list(query_list):
    """クエリ要素のリストからクエリ文字列を作成"""
    if not query_list or len(query_list) == 0:
        return ''
    if len(query_list) == 1:
        return query_list[0]
    return '(' + ' '.join(query_list) + ')'

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

@app.route('/api/start_analysis', methods=['POST'])
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

        # 処理対象を計算（トレンドワードがある作品は2回解析するため）
        total_tasks = 0
        for display_name in query_dict.keys():
            if trend_flags.get(display_name, False):
                # トレンド専用クエリは1回のみ
                total_tasks += 1
            else:
                # 通常作品
                trends = trend_map.get(display_name, [])
                if trends:
                    # トレンドワードがある場合は2回（元のクエリのみ + トレンド付き）
                    total_tasks += 2
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
                original_query_elements = original_queries.get(display_name, [query_string])
                
                # トレンドワードが元のクエリに含まれているかチェック
                new_trends = [t for t in trends if t not in original_query_elements]
                
                if new_trends:
                    # トレンドワードがあり、元のクエリに含まれていない場合
                    # 1. 元のクエリのみで解析
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
                    # トレンドワードがないか、元のクエリに含まれている場合は1回のみ
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
            # isTrendがTrueの場合はスキップ
            if result.get('isTrend', False):
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
            # トレンドワードのマッピングを作成（作品名をキーとする）
            trend_map = {}
            for t in trend_words_data:
                if t.get('word', '').strip() and t.get('workName', '').strip():
                    trend_map[t['workName']] = {'word': t['word'], 'rank': t.get('rank', '')}
            
            # トレンドワードの新しいデータを準備
            trend_new_rows = []
            
            # 作品に紐づいたトレンドワード情報を保存（withTrendWord=Trueの結果から）
            for result in analysis_results:
                if result.get('withTrendWord', False) and not result.get('isTrend', False):
                    work_name = result['作品名']
                    trend_words_list = result.get('trendWords', [])
                    
                    # 対応するトレンド情報を取得
                    trend_info = trend_map.get(work_name, {})
                    trend_word = '+'.join(trend_words_list) if trend_words_list else trend_info.get('word', '')
                    
                    if not trend_word:
                        continue
                    
                    trend_new_row = {
                        '号数': issue_number,
                        '作品名': work_name,
                        'トレンドワード': trend_word,
                        '順位': trend_info.get('rank', ''),
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
