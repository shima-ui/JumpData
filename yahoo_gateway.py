"""
Yahoo API統合モジュール
Yahooリアルタイム検索APIとの通信を管理
"""
import re
import requests
from datetime import datetime
from zoneinfo import ZoneInfo


# ヘッダー設定
Headers = {"User-Agent": "Mozilla/5.0"}

# クラムトークンの管理
CRUMB_COUNT = 0
CRUMB_REUSE_COUNT = 20
CRUMB = None


class YahooGateway:
    """Yahooリアルタイム検索APIのゲートウェイクラス"""
    
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
            return None
    
    def get_yahoo_word_counts(self, word: str, interval_hour: int = 24, span_hour: int = 30 * 24) -> list[dict]:
        """Yahooリアルタイム検索で指定されたワードのポスト数を取得する。
        
        Args:
            word: 検索ワード
            interval_hour: 集計間隔（時間）
            span_hour: 取得期間（時間）
            
        Returns:
            list[dict]: ポスト数のリスト
        """
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
