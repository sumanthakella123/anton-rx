"use client";

import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAISDKRuntime } from "@assistant-ui/react-ai-sdk";
import { Thread } from "@/components/assistant-ui/thread";
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar";
import { ThreadListSidebar } from "@/components/assistant-ui/threadlist-sidebar";
import { Separator } from "@/components/ui/separator";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { useEffect, useMemo } from "react";
import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport } from "ai";
import { useChatStore } from "@/lib/chat-store";

export const Assistant = () => {
  const { isLoaded, activeThreadId, threads, loadThreads } = useChatStore();

  useEffect(() => {
    loadThreads();
  }, [loadThreads]);

  if (!isLoaded || !activeThreadId) return null;

  const activeThread = threads.find((t) => t.id === activeThreadId);

  return (
    <SidebarProvider>
      <div className="flex h-dvh w-full pr-0.5">
        <ThreadListSidebar />
        <SidebarInset>
          <header className="flex h-16 shrink-0 items-center gap-2 border-b px-4">
            <SidebarTrigger />
            <Separator orientation="vertical" className="mr-2 h-4" />
            <Breadcrumb>
              <BreadcrumbList>
                <BreadcrumbItem className="hidden md:block">
                  <BreadcrumbLink href="#">Anton Rx System</BreadcrumbLink>
                </BreadcrumbItem>
                <BreadcrumbSeparator className="hidden md:block" />
                <BreadcrumbItem>
                  <BreadcrumbPage>Medical Policy Assistant</BreadcrumbPage>
                </BreadcrumbItem>
              </BreadcrumbList>
            </Breadcrumb>
          </header>
          <div className="flex-1 overflow-hidden">
            <ActiveThread
              key={activeThreadId}
              threadId={activeThreadId}
              initialMessages={activeThread?.messages ?? []}
            />
          </div>
        </SidebarInset>
      </div>
    </SidebarProvider>
  );
};

const ActiveThread = ({
  threadId,
  initialMessages,
}: {
  threadId: string;
  initialMessages: any[];
}) => {
  const { updateThreadMessages } = useChatStore();

  const transport = useMemo(() => new DefaultChatTransport(), []);

  const chat = useChat({
    transport,
    messages: initialMessages,
  });

  const runtime = useAISDKRuntime(chat);

  useEffect(() => {
    if (chat.messages.length > 0) {
      updateThreadMessages(threadId, chat.messages);
    }
  }, [chat.messages, threadId, updateThreadMessages]);

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <Thread />
    </AssistantRuntimeProvider>
  );
};
