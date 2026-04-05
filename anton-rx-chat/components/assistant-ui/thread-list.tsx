"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/lib/chat-store";
import { PlusIcon, Trash2Icon } from "lucide-react";
import type { FC } from "react";

export const ThreadList: FC = () => {
  const { threads, activeThreadId, createThread, switchThread, removeThread } =
    useChatStore();

  return (
    <div className="flex flex-col gap-1">
      <Button
        variant="outline"
        className="h-9 justify-start gap-2 rounded-lg px-3 text-sm hover:bg-muted"
        onClick={() => createThread()}
      >
        <PlusIcon className="size-4" />
        New Thread
      </Button>

      {threads.map((thread) => (
        <div
          key={thread.id}
          className={cn(
            "group flex h-9 items-center gap-2 rounded-lg transition-colors hover:bg-muted focus-visible:outline-none",
            activeThreadId === thread.id && "bg-muted",
          )}
        >
          <button
            className="flex h-full min-w-0 flex-1 items-center truncate px-3 text-start text-sm"
            onClick={() => switchThread(thread.id)}
          >
            {thread.title}
          </button>

          <Button
            variant="ghost"
            size="icon"
            className="mr-2 size-7 shrink-0 p-0 opacity-0 transition-opacity group-hover:opacity-100"
            onClick={(e) => {
              e.stopPropagation();
              removeThread(thread.id);
            }}
          >
            <Trash2Icon className="size-4" />
            <span className="sr-only">Delete</span>
          </Button>
        </div>
      ))}
    </div>
  );
};
