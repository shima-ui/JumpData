import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import numpy as np
from config import QUERY_DICT, INTERVAL_HOUR, SPAN_HOUR, REFERENCE_BASE_DATETIME

# --- YahooGateway クラスの定義 ---
Headers = {"User-Agent": "Mozilla/5.0"}
CRUMB_COUNT = 0  # クッキーのクラムトークン取得回数
CRUMB_REUSE_COUNT = 20  # クラムトークンの再利用回数
CRUMB = None  # クラムトークンの初期値

class YahooGateway():
    def _get_crumb_token(self) -> str:
        """Yahooリアルタイム検索のクラムトークンを取得する。

        Returns:
            str: クラムトークン
        """
        try:
            global CRUMB, CRUMB_COUNT
            if CRUMB_COUNT >= CRUMB_REUSE_COUNT or CRUMB is None:
                session = requests.Session()
                response = session.get("https://search.yahoo.co.jp/realtime/search?p=x.com", headers=Headers)
                response.raise_for_status()  # ステータスコードが200以外の場合例外を発生
                crumb_match = re.search(r'"crumb"\s*:\s*"([^"]+)"', response.text)
                CRUMB = crumb_match.group(1) if crumb_match else None
                CRUMB_COUNT = 0
            else:
                CRUMB_COUNT += 1
            return CRUMB
        except Exception as e:
            print(f"Error fetching Yahoo crumb token: {str(e)}")

    def get_yahoo_word_counts(self, word: str, interval_hour: int = 24, span_hour: int = 30 * 24) -> list[dict]:
        """Yahooリアルタイム検索で指定されたワードのポスト数を取得する。

        Args:
            word (str): 検索ワード
            interval_hour (int): ポスト数の集計間隔（時間単位）
            span_hour (int): 集計期間（時間単位）

        Returns:
            list: 検索結果のポスト数リスト
        """
        try:
            crumb = self._get_crumb_token()
            params = {
                "crumb": crumb,
                "p": word,
                "interval": int(interval_hour * 60 * 60),  # 秒に変換
                "span": span_hour * 60 * 60,  # 秒に変換
            }
            session = requests.Session()
            response = session.get("https://search.yahoo.co.jp/realtime/api/v1/transition", params=params)
            response.raise_for_status()  # ステータスコードが200以外の場合例外を発生

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

def main():
    # config.pyからクエリとパラメータを使用
    query_dict = QUERY_DICT
    interval_hour = INTERVAL_HOUR
    span_hour = SPAN_HOUR

    yahoo_gateway = YahooGateway()

    summary_data = []  # 新しいリストを初期化して、結果を格納する

    for display_name, query_string in query_dict.items():
        print(f"\nProcessing for: {display_name} (Query: {query_string})")

        # --- データの取得と整形 ---
        yahoo_word_counts = yahoo_gateway.get_yahoo_word_counts(query_string, interval_hour, span_hour)

        if not yahoo_word_counts:
            print(f"No data retrieved for '{display_name}'. Skipping visualization.")
            # データが取得できなかった場合もサマリーに追加する
            summary_data.append({
                '作品名': display_name,
                'クエリ': query_string,
                '参照カウント': np.nan,
                '合計カウント': np.nan,
                '合計カウント終了時刻': 'データなし'
            })
            continue

        df_yahoo_word_counts = pd.DataFrame(yahoo_word_counts)
        df_yahoo_word_counts['from_date'] = pd.to_datetime(df_yahoo_word_counts['from_date'])

        # --- 参照点の特定 ---
        # 参照日時計算の基準となる日時を設定
        reference_base_datetime = pd.to_datetime(REFERENCE_BASE_DATETIME)
        
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
            print(f"参照時刻範囲: {reference_times[0].strftime('%H:%M')}-{reference_times[-1].strftime('%H:%M')}")
            print(f"参照カウント (平均): {reference_count:.2f} (データ数: {len(reference_counts)})")
        else:
            print(f"参照時刻範囲のデータが見つかりませんでした。デフォルト値 0 を使用します。")
            reference_count = 0

        # --- 合計カウントの計算 ---
        df_sum_calculation = df_yahoo_word_counts[df_yahoo_word_counts['from_date'] >= reference_base_datetime].copy()

        # Define the minimum duration for the summation period (1 hour)
        min_sum_duration_end_time = reference_base_datetime + timedelta(hours=1)

        # Initialize the actual end time for summation
        actual_sum_end_datetime = None

        if not df_sum_calculation.empty:
            # Find the first data point where the count drops to or below the reference_count
            natural_end_candidates = df_sum_calculation[df_sum_calculation['count'] <= reference_count]

            if not natural_end_candidates.empty:
                natural_sum_end_datetime = natural_end_candidates['from_date'].min()
            else:
                natural_sum_end_datetime = None  # Count never drops

            # Determine the actual end time based on the conditions
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

        if actual_sum_end_datetime:
            df_sum_range = df_sum_calculation[df_sum_calculation['from_date'] < actual_sum_end_datetime].copy()
        else:
            df_sum_range = pd.DataFrame()  # Empty DataFrame if no data

        sum_end_datetime_for_print = actual_sum_end_datetime

        sum_value = df_sum_range['count'].sum() if not df_sum_range.empty else 0
        print(f"計算された合計カウント: {sum_value:.2f}")

        print(f"合計カウント開始日時: {reference_base_datetime}")
        print(f"合計カウント終了日時: {sum_end_datetime_for_print if sum_end_datetime_for_print else 'データなし'}")

        # 結果をリストに追加
        summary_data.append({
            '作品名': display_name,
            'クエリ': query_string,
            '参照カウント': reference_count,
            '合計カウント': sum_value,
            '合計カウント終了時刻': sum_end_datetime_for_print.strftime('%Y-%m-%d %H:%M:%S') if sum_end_datetime_for_print else 'データなし'
        })



    # ループ終了後、summary_dataからDataFrameを作成し表示
    df_summary = pd.DataFrame(summary_data)
    print("\n" + "="*80)
    print("サマリー:")
    print("="*80)
    print(df_summary.to_string(index=False))
    
    # CSVファイルとして保存
    output_filename = 'yahoo_word_analysis_summary.csv'
    df_summary.to_csv(output_filename, index=False, encoding='utf-8-sig')
    print(f"\nサマリーデータを '{output_filename}' に保存しました。")

if __name__ == "__main__":
    main()
