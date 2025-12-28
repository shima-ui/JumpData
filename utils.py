"""
汎用ユーティリティ関数モジュール
データ変換やクエリ構築などの補助機能を提供
"""
import numpy as np
import pandas as pd


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


def format_datetime(dt):
    """タイムゾーン情報を除去して文字列化する関数"""
    if hasattr(dt, 'tz_localize'):
        return dt.tz_localize(None).strftime('%Y-%m-%d %H:%M:%S')
    elif hasattr(dt, 'strftime'):
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    else:
        return str(dt)


def build_query_from_list(query_list):
    """クエリ要素のリストからクエリ文字列を作成"""
    if not query_list or len(query_list) == 0:
        return ''
    if len(query_list) == 1:
        return query_list[0]
    return '(' + ' '.join(query_list) + ')'
