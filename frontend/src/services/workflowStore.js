const DB_NAME = "ai-data-analytics-workspace";
const STORE_NAME = "workflow-results";
const DB_VERSION = 1;

function openDatabase() {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("IndexedDB is unavailable in this browser."));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "datasetId" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("Unable to open workflow storage."));
  });
}

async function runTransaction(mode, operation) {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, mode);
    const store = transaction.objectStore(STORE_NAME);
    let result;
    try { result = operation(store); } catch (error) { db.close(); reject(error); return; }
    transaction.oncomplete = () => { db.close(); resolve(result?.result); };
    transaction.onerror = () => { db.close(); reject(transaction.error || new Error("Workflow storage transaction failed.")); };
    transaction.onabort = () => { db.close(); reject(transaction.error || new Error("Workflow storage transaction was aborted.")); };
  });
}

export async function getAllWorkflowResults() {
  const db = await openDatabase();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).getAll();
    request.onsuccess = () => { db.close(); resolve(request.result || []); };
    request.onerror = () => { db.close(); reject(request.error || new Error("Unable to read workflow history.")); };
  });
}

export function saveWorkflowResult(datasetId, stage, result) {
  return runTransaction("readwrite", (store) => {
    const request = store.get(String(datasetId));
    request.onsuccess = () => {
      const current = request.result || { datasetId: String(datasetId), stages: {} };
      current.stages = { ...current.stages, [stage]: { result, savedAt: new Date().toISOString() } };
      store.put(current);
    };
    return request;
  });
}

export function deleteWorkflowResult(datasetId) {
  return runTransaction("readwrite", (store) => store.delete(String(datasetId)));
}
