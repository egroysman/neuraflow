import type { Metadata } from "next";

export const metadata: Metadata = { title: "Workspaces · NeuraFlow" };

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
