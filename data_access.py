"""
データアクセス層モジュール
CSVファイルの読み書きと号数-日付マッピング管理
"""
import os
import pandas as pd


# 号数-日付マッピングのキャッシュ
issue_date_mapping_cache = None


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


def load_summary_data():
    """yahoo_word_analysis_summary.csvを読み込む"""
    csv_filename = 'yahoo_word_analysis_summary.csv'
    if not os.path.exists(csv_filename):
        raise FileNotFoundError("データファイルが見つかりません")
    
    df = pd.read_csv(csv_filename, encoding='utf-8-sig')
    return df


def load_trend_data():
    """yahoo_trend_analysis_summary.csvを読み込む"""
    csv_filename = 'yahoo_trend_analysis_summary.csv'
    if not os.path.exists(csv_filename):
        return pd.DataFrame()  # 空のDataFrameを返す
    
    df = pd.read_csv(csv_filename, encoding='utf-8-sig')
    return df


def save_analysis_to_csv(analysis_results, issue_number, trend_words_data):
    """解析結果をCSVデータベースファイルに保存・更新
    
    Args:
        analysis_results: 解析結果のリスト
        issue_number: 号数
        trend_words_data: トレンドワード情報
        
    Returns:
        dict: 保存結果の情報
    """
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
    
    return {
        'saved_count': len(new_rows),
        'trend_saved_count': trend_saved_count
    }
