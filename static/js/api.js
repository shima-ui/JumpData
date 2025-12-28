/**
 * API通信モジュール
 * バックエンドとのデータ送受信を管理
 */

/**
 * クエリ情報と号数マッピングを取得
 */
export async function fetchQueries() {
    const response = await fetch('/api/get_queries');
    if (!response.ok) {
        throw new Error('クエリの取得に失敗しました');
    }
    return await response.json();
}

/**
 * 解析を開始
 */
export async function startAnalysis(queries, referenceIssueNumber, trendWords, originalQueries) {
    const response = await fetch('/api/start_analysis', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            queries,
            reference_issue_number: referenceIssueNumber,
            trend_words: trendWords,
            original_queries: originalQueries
        })
    });
    
    if (!response.ok) {
        throw new Error('解析の開始に失敗しました');
    }
    
    return await response.json();
}

/**
 * 解析の進捗を取得
 */
export async function fetchProgress() {
    const response = await fetch('/api/progress');
    if (!response.ok) {
        throw new Error('進捗の取得に失敗しました');
    }
    return await response.json();
}

/**
 * 解析結果を取得
 */
export async function fetchResults() {
    const response = await fetch('/api/results');
    if (!response.ok) {
        throw new Error('結果の取得に失敗しました');
    }
    return await response.json();
}

/**
 * 結果をCSVに保存
 */
export async function saveToCSV(issueNumber, trendWords) {
    const response = await fetch('/api/save_to_csv', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            issue_number: issueNumber,
            trend_words: trendWords
        })
    });
    
    if (!response.ok) {
        throw new Error('CSV保存に失敗しました');
    }
    
    return await response.json();
}
