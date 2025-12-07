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

@app.route('/api/get_queries')
def get_queries():
    """デフォルトのクエリ辞書と基準号数を取得"""
    queries = [{'name': k, 'query': v} for k, v in QUERY_DICT.items()]
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
    
    # クエリが空の場合はデフォルトを使用
    if not queries:
        queries = [{'name': k, 'query': v} for k, v in QUERY_DICT.items()]
    
    # 別スレッドで解析を実行
    import threading
    thread = threading.Thread(target=run_analysis, args=(queries, reference_issue_number))
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Analysis started"})

def run_analysis(queries, reference_issue_number=None):
    """解析を実行(バックグラウンド)"""
    global analysis_results, analysis_progress
    
    try:
        # クエリをリストから辞書に変換
        query_dict = {q['name']: q['query'] for q in queries}

        interval_hour = INTERVAL_HOUR
        span_hour = SPAN_HOUR
        # 号数から日付を取得
        if reference_issue_number is None:
            reference_issue_number = REFERENCE_ISSUE_NUMBER
        reference_base_datetime = get_date_from_issue_number(reference_issue_number)
        
        if reference_base_datetime is None:
            raise ValueError(f"号数 {reference_issue_number} に対応する日付が見つかりません")

        analysis_progress["total"] = len(query_dict)
        summary_data = []

        for idx, (display_name, query_string) in enumerate(query_dict.items(), 1):
            analysis_progress["current"] = idx
            analysis_progress["message"] = f"処理中: {display_name}"
            
            result = analyze_word(display_name, query_string, interval_hour, span_hour, reference_base_datetime)
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

@app.route('/api/download_csv')
def download_csv():
    """CSV形式で結果をダウンロード"""
    if analysis_results is None:
        return jsonify({"error": "No results available"}), 404
    
    # chart_data, range_dataなどのグラフ用データを除外してCSV作成
    df_results = pd.DataFrame([{k: v for k, v in r.items() if k not in ['chart_data', 'one_hour_range_data', 'after_one_hour_range_data', 'reference_datetime', 'reference_base_datetime']} for r in analysis_results])
    
    output = io.StringIO()
    df_results.to_csv(output, index=False, encoding='utf-8-sig')
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')),
        mimetype='text/csv',
        as_attachment=True,
        download_name='yahoo_word_analysis_results.csv'
    )

@app.route('/static/images/<path:filename>')
def serve_image(filename):
    """画像ファイルを提供する"""
    images_dir = os.path.join(os.path.dirname(__file__), 'images')
    return send_from_directory(images_dir, filename)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
