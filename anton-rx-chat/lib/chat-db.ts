import { openDB, type IDBPDatabase } from "idb";

export interface ChatThread {
  id: string;
  title: string;
  messages: any[];
  createdAt: number;
  updatedAt: number;
}

const DB_NAME = "anton-rx-chat";
const DB_VERSION = 1;
const STORE = "threads";

let _db: Promise<IDBPDatabase> | null = null;

function getDb(): Promise<IDBPDatabase> {
  if (!_db) {
    _db = openDB(DB_NAME, DB_VERSION, {
      upgrade(db) {
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: "id" });
        }
      },
    });
  }
  return _db;
}

export async function getAllThreads(): Promise<ChatThread[]> {
  const db = await getDb();
  const all = await db.getAll(STORE);
  return (all as ChatThread[]).sort((a, b) => b.updatedAt - a.updatedAt);
}

export async function putThread(thread: ChatThread): Promise<void> {
  const db = await getDb();
  await db.put(STORE, thread);
}

export async function deleteThread(id: string): Promise<void> {
  const db = await getDb();
  await db.delete(STORE, id);
}
