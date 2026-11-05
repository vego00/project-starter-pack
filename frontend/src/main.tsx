import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./style.css";

// Mock-only screen, loaded on demand so the journey never downloads the graph library.
const DesignStudio = lazy(() => import("./design/DesignStudio"));
const isDesignMock =
  new URLSearchParams(window.location.search).get("mock") === "design";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {isDesignMock ? (
      <Suspense
        fallback={<p className="panel muted">화면을 불러오는 중이에요…</p>}
      >
        <DesignStudio />
      </Suspense>
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
