"""
分析ロジックモジュール
Yahoo検索データの分析と解析処理
"""
from datetime import timedelta
import pandas as pd
import numpy as np

from yahoo_gateway import YahooGateway
from utils import format_datetime, build_query_from_list
from data_access import get_date_from_issue_number
from config import QUERY_DICT, INTERVAL_HOUR, SPAN_HOUR, REFERENCE_ISSUE_NUMBER


# グローバル変数（進捗状態管理）
analysis_results = None
analysis_progress = {"current": 0, "total": 0, "status": "idle", "message": ""}


def analyze_word(display_name, query_string, interval_hour, span_hour, reference_base_datetime):
    """単一のワードを解析
    
    Args:
        display_name: 表示名（作品名）
        query_string: 検索クエリ文字列
        interval_hour: 集計間隔（時間）
        span_hour: 取得期間（時間）
        reference_base_datetime: 基準日時
        
    Returns:
        dict: 解析結果
    """
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
    # 参照値を差し引いた1時間集計（負の値にならないようmax(0, ...)で処理）
    one_hour_sum_value = df_one_hour_range.apply(
        lambda row: max(0, row['count'] - reference_count), axis=1
    ).sum() if not df_one_hour_range.empty else 0
    
    # 参照値を下回るまでの集計範囲（現行）
    if actual_sum_end_datetime:
        df_sum_range = df_sum_calculation[df_sum_calculation['from_date'] < actual_sum_end_datetime].copy()
    else:
        df_sum_range = pd.DataFrame()

    # 参照値を差し引いた全体集計（負の値にならないようmax(0, ...)で処理）
    sum_value = df_sum_range.apply(
        lambda row: max(0, row['count'] - reference_count), axis=1
    ).sum() if not df_sum_range.empty else 0
    
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


def run_analysis(queries, reference_issue_number=None, trend_words_data=None, original_queries=None):
    """解析を実行(バックグラウンド)
    
    Args:
        queries: クエリリスト
        reference_issue_number: 基準号数
        trend_words_data: トレンドワード情報
        original_queries: 元のクエリ情報
    """
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


def get_analysis_results():
    """解析結果を取得"""
    return analysis_results


def get_analysis_progress():
    """解析進捗を取得"""
    return analysis_progress


def reset_analysis_progress():
    """解析進捗をリセット"""
    global analysis_progress, analysis_results
    analysis_progress = {"current": 0, "total": 0, "status": "running", "message": "初期化中..."}
    analysis_results = None
