import type { Metadata } from "next";
import DataApp from "./DataApp";

export const metadata: Metadata = {
  title: "Data · NeuraFlow",
  description: "Connect your files, warehouse or SFTP drop folder.",
};

export default function DataPage() {
  return <DataApp />;
}
