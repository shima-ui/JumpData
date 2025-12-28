/**
 * アプリケーション状態管理モジュール
 * グローバル状態変数とアクセサーを提供
 */

// 進捗監視用のインターバルID
let progressInterval = null;

// クエリ関連の状態
let currentQueries = [];
let originalQueries = {}; // 元のクエリを保持 {作品名: [クエリ要素のリスト]}
let querySelections = {}; // 各作品の選択状態を保持

// 号数と日付のマッピング
let currentReferenceIssueNumber = 1;
let issueDateMapping = {};

// トレンドワード関連
let trendWords = []; // [{word: "", workName: "", rank: ""}]

// 結果関連
let currentResults = null;
let currentReportTab = 'total';

// ソート状態
let currentSortColumn = 'total';
let currentSortDirection = 'desc';

/**
 * 進捗インターバルの取得・設定
 */
export function getProgressInterval() {
    return progressInterval;
}

export function setProgressInterval(interval) {
    progressInterval = interval;
}

export function clearProgressInterval() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
}

/**
 * クエリ関連の状態
 */
export function getCurrentQueries() {
    return currentQueries;
}

export function setCurrentQueries(queries) {
    currentQueries = queries;
}

export function getOriginalQueries() {
    return originalQueries;
}

export function setOriginalQueries(queries) {
    originalQueries = queries;
}

export function updateOriginalQuery(name, queryList) {
    originalQueries[name] = queryList;
}

export function getQuerySelections() {
    return querySelections;
}

export function setQuerySelections(selections) {
    querySelections = selections;
}

export function updateQuerySelection(index, isSelected) {
    querySelections[index] = isSelected;
}

/**
 * 号数と日付のマッピング
 */
export function getCurrentReferenceIssueNumber() {
    return currentReferenceIssueNumber;
}

export function setCurrentReferenceIssueNumber(issueNumber) {
    currentReferenceIssueNumber = issueNumber;
}

export function getIssueDateMapping() {
    return issueDateMapping;
}

export function setIssueDateMapping(mapping) {
    issueDateMapping = mapping;
}

/**
 * トレンドワード関連
 */
export function getTrendWords() {
    return trendWords;
}

export function setTrendWords(words) {
    trendWords = words;
}

export function addTrendWord(word) {
    trendWords.push(word);
}

export function removeTrendWord(index) {
    trendWords.splice(index, 1);
}

export function updateTrendWord(index, word) {
    trendWords[index] = word;
}

/**
 * 結果関連
 */
export function getCurrentResults() {
    return currentResults;
}

export function setCurrentResults(results) {
    currentResults = results;
}

export function getCurrentReportTab() {
    return currentReportTab;
}

export function setCurrentReportTab(tab) {
    currentReportTab = tab;
}

/**
 * ソート状態
 */
export function getCurrentSortColumn() {
    return currentSortColumn;
}

export function setCurrentSortColumn(column) {
    currentSortColumn = column;
}

export function getCurrentSortDirection() {
    return currentSortDirection;
}

export function setCurrentSortDirection(direction) {
    currentSortDirection = direction;
}

export function toggleSortDirection() {
    currentSortDirection = currentSortDirection === 'asc' ? 'desc' : 'asc';
}
