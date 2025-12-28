"""
Flaskアプリケーションのメインファイル
APIルーティングとリクエストハンドリング
"""
from flask import Flask, render_template, jsonify, request, send_from_directory
import os
import threading

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
from threading import Lock
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


@app.route('/api/start_analysis', methods=['POST'])
def start_analysis():
    """解析を開始"""
    with analysis_lock:
        progress = get_analysis_progress()
        if progress["status"] == "running":
            return jsonify({"error": "Analysis already running"}), 400
        
        reset_analysis_progress()
    
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
    thread = threading.Thread(
        target=run_analysis,
        args=(queries, reference_issue_number, trend_words_data, original_queries)
    )
    thread.daemon = True
    thread.start()
    
    return jsonify({"message": "Analysis started"})


@app.route('/api/progress')
def get_progress():
    """解析の進捗を取得"""
    progress = get_analysis_progress()
    return jsonify(progress)


@app.route('/api/results')
def get_results():
    """解析結果を取得"""
    results = get_analysis_results()
    if results is None:
        return jsonify({"error": "No results available"}), 404
    
    # NumPy/Pandasのデータ型をJSON serializable な型に変換
    serializable_results = []
    for result in results:
        serializable_result = {k: convert_to_serializable(v) for k, v in result.items()}
        serializable_results.append(serializable_result)
    
    return jsonify({"results": serializable_results})


@app.route('/api/save_to_csv', methods=['POST'])
def save_to_csv():
    """解析結果をCSVデータベースファイルに保存・更新"""
    results = get_analysis_results()
    if results is None:
        return jsonify({"error": "No results available"}), 404
    
    try:
        # リクエストから号数とトレンドワード情報を取得
        data = request.get_json()
        issue_number = data.get('issue_number', REFERENCE_ISSUE_NUMBER)
        trend_words_data = data.get('trend_words', [])  # [{word, workName, rank}, ...]
        
        # データアクセス層の関数を使用して保存
        save_result = save_analysis_to_csv(results, issue_number, trend_words_data)
        
        message = f"データを保存しました (作品: {save_result['saved_count']}件"
        if save_result['trend_saved_count'] > 0:
            message += f", トレンド: {save_result['trend_saved_count']}件"
        message += ")"
        
        return jsonify({
            "message": message,
            "issue_number": issue_number,
            "saved_count": save_result['saved_count'],
            "trend_saved_count": save_result['trend_saved_count']
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
