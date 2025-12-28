/**
 * ユーティリティ関数モジュール
 * 汎用的な処理を提供
 */

/**
 * 画像URLを取得
 */
export function getImageUrl(queryName) {
    return `/static/images/${queryName}.jpg`;
}

/**
 * クエリ要素のリストからクエリ文字列を作成
 */
export function buildQueryFromList(queryList) {
    if (!queryList || queryList.length === 0) return '';
    if (queryList.length === 1) return queryList[0];
    return '(' + queryList.join(' ') + ')';
}

/**
 * クエリ文字列をリストに分解
 */
export function parseQueryToList(queryString) {
    // 括弧を取り除いてスペースで分割
    const cleaned = queryString.replace(/^\(+|\)+$/g, '').trim();
    return cleaned ? [cleaned] : [];
}

/**
 * トレンドワードを作品別にマッピング
 */
export function getTrendWordsMap(trendWords) {
    const trendMap = {};
    trendWords.forEach(trend => {
        if (trend.word && trend.workName) {
            if (!trendMap[trend.workName]) {
                trendMap[trend.workName] = [];
            }
            trendMap[trend.workName].push(trend.word);
        }
    });
    return trendMap;
}

/**
 * ソートアイコンを取得
 */
export function getSortIcon(columnName, currentColumn, currentDirection) {
    if (columnName === currentColumn) {
        return currentDirection === 'asc' ? '▲' : '▼';
    }
    return '';
}

/**
 * データをソート
 */
export function sortData(data, column, direction) {
    return [...data].sort((a, b) => {
        let aVal = a[column];
        let bVal = b[column];
        
        // 数値の場合
        if (typeof aVal === 'number' && typeof bVal === 'number') {
            return direction === 'asc' ? aVal - bVal : bVal - aVal;
        }
        
        // 文字列の場合
        aVal = String(aVal || '');
        bVal = String(bVal || '');
        
        if (direction === 'asc') {
            return aVal.localeCompare(bVal, 'ja');
        } else {
            return bVal.localeCompare(aVal, 'ja');
        }
    });
}

/**
 * 作品結果をグループ化（トレンドありとトレンドなしをまとめる）
 */
export function groupResultsByWork(results) {
    const groupedResults = {};
    
    results.forEach(result => {
        const workName = result['作品名'];
        if (!groupedResults[workName]) {
            groupedResults[workName] = {
                base: null,      // トレンドなし
                withTrend: null  // トレンドあり
            };
        }
        if (result.withTrendWord) {
            groupedResults[workName].withTrend = result;
        } else {
            groupedResults[workName].base = result;
        }
    });
    
    return groupedResults;
}

/**
 * サマリーデータを作成
 */
export function createSummaryData(groupedResults) {
    const summaryData = [];
    
    Object.keys(groupedResults).forEach(workName => {
        const group = groupedResults[workName];
        const baseResult = group.base;
        const trendResult = group.withTrend;
        
        if (!baseResult && !trendResult) return;
        
        const mainResult = baseResult || trendResult;
        const hasTrend = trendResult !== null;
        
        // トレンドありの値を優先、なければトレンドなしの値を使用
        const reference = mainResult['参照カウント'] !== null ? mainResult['参照カウント'] : 0;
        const oneHour = trendResult ? 
            (trendResult['1時間集計'] !== null ? trendResult['1時間集計'] : 0) :
            (baseResult && baseResult['1時間集計'] !== null ? baseResult['1時間集計'] : 0);
        const total = trendResult ? 
            (trendResult['全体集計'] !== null ? trendResult['全体集計'] : 0) :
            (baseResult && baseResult['全体集計'] !== null ? baseResult['全体集計'] : 0);
        
        summaryData.push({
            workName: workName,
            reference: reference,
            oneHour: oneHour,
            total: total,
            endTime: mainResult['全体集計終了時刻'],
            hasTrend: hasTrend,
            trendWords: hasTrend ? trendResult.trendWords : []
        });
    });
    
    return summaryData;
}

/**
 * ランキングデータを作成
 */
export function createRankingData(groupedResults, sortKey = '全体集計', limit = 10) {
    const workSummaries = [];
    
    Object.keys(groupedResults).forEach(workName => {
        const group = groupedResults[workName];
        const baseResult = group.base;
        const trendResult = group.withTrend;
        
        // トレンドありの値を優先、なければトレンドなしの値を使用
        const totalCount = trendResult ? 
            (trendResult[sortKey] !== null ? trendResult[sortKey] : 0) :
            (baseResult && baseResult[sortKey] !== null ? baseResult[sortKey] : 0);
        
        const baseCount = baseResult && baseResult[sortKey] !== null ? baseResult[sortKey] : 0;
        const trendOnlyCount = totalCount - baseCount;
        
        workSummaries.push({
            workName: workName,
            totalCount: totalCount,
            baseCount: baseCount,
            trendOnlyCount: trendOnlyCount,
            hasTrend: trendResult !== null,
            trendWords: trendResult ? trendResult.trendWords : []
        });
    });
    
    // 合計ツイート数でソートして上位を返す
    return workSummaries
        .filter(s => s.totalCount > 0)
        .sort((a, b) => b.totalCount - a.totalCount)
        .slice(0, limit);
}
