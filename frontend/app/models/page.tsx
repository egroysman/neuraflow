import type { Metadata } from "next";
import ModelsApp from "./ModelsApp";

export const metadata: Metadata = {
  title: "Models · NeuraFlow",
  description: "The prediction models running behind NeuraFlow, tested against simple rules.",
};

export default function ModelsPage() {
  return <ModelsApp />;
}
