import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "@fontsource/ibm-plex-sans-kr/400.css";
import "@fontsource/ibm-plex-sans-kr/500.css";
import "@fontsource/ibm-plex-sans-kr/700.css";
import "./style.css";

// Loaded on demand so the journey never downloads the graph library.
const DesignStudio = lazy(() => import("./design/DesignStudio"));
const params = new URLSearchParams(window.location.search);
const designJourneyId = params.get("design");
const isDesignMock = params.get("mock") === "design";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {designJourneyId || isDesignMock ? (
      <Suspense
        fallback={<p className="panel muted">화면을 불러오는 중이에요…</p>}
      >
        <DesignStudio journeyId={designJourneyId} />
      </Suspense>
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
