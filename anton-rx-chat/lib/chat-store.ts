import { create } from "zustand";
import {
  getAllThreads,
  putThread,
  deleteThread as dbDelete,
  type ChatThread,
} from "./chat-db";

function newId() {
  return crypto.randomUUID();
}

function newThread(): ChatThread {
  const now = Date.now();
  return { id: newId(), title: "New Chat", messages: [], createdAt: now, updatedAt: now };
}

interface ChatStoreState {
  threads: ChatThread[];
  activeThreadId: string | null;
  isLoaded: boolean;

  loadThreads: () => Promise<void>;
  createThread: () => Promise<void>;
  switchThread: (id: string) => void;
  updateThreadMessages: (id: string, messages: any[]) => Promise<void>;
  removeThread: (id: string) => Promise<void>;
}

export const useChatStore = create<ChatStoreState>((set, get) => ({
  threads: [],
  activeThreadId: null,
  isLoaded: false,

  loadThreads: async () => {
    const threads = await getAllThreads();
    if (threads.length === 0) {
      const t = newThread();
      await putThread(t);
      set({ threads: [t], activeThreadId: t.id, isLoaded: true });
    } else {
      set({ threads, activeThreadId: threads[0].id, isLoaded: true });
    }
  },

  createThread: async () => {
    const t = newThread();
    await putThread(t);
    set((s) => ({ threads: [t, ...s.threads], activeThreadId: t.id }));
  },

  switchThread: (id) => set({ activeThreadId: id }),

  updateThreadMessages: async (id, messages) => {
    const thread = get().threads.find((t) => t.id === id);
    if (!thread) return;

    let title = thread.title;
    if (title === "New Chat" && messages.length > 0) {
      const first = messages.find((m: any) => m.role === "user");
      if (first) {
        const textPart = first.parts?.find((p: any) => p.type === "text");
        const raw: string = textPart?.text ?? (typeof first.content === "string" ? first.content : "");
        title = raw.trim().slice(0, 45) || "Chat";
      }
    }

    const updated: ChatThread = { ...thread, title, messages, updatedAt: Date.now() };
    await putThread(updated);
    set((s) => ({ threads: s.threads.map((t) => (t.id === id ? updated : t)) }));
  },

  removeThread: async (id) => {
    await dbDelete(id);
    const remaining = get().threads.filter((t) => t.id !== id);

    if (remaining.length === 0) {
      const t = newThread();
      await putThread(t);
      set({ threads: [t], activeThreadId: t.id });
      return;
    }

    const newActive =
      get().activeThreadId === id ? remaining[0].id : get().activeThreadId;
    set({ threads: remaining, activeThreadId: newActive });
  },
}));
