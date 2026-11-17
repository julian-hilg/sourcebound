import { activityTool } from "./activity";
import { assetsTool } from "./assets";
import { checkTool } from "./check";
import { claimsTool } from "./claims";
import { connectionsTool } from "./connections";
import { deliverableTool } from "./deliverable";
import { deliverablesTool } from "./deliverables";
import { documentsTool, reviewsTool } from "./documents";
import { fetchLogTool } from "./fetchlog";
import { defineHub } from "./hub";
import { hypothesesTool } from "./hypotheses";
import { jobsTool } from "./jobs";
import { pieceTool } from "./piece";
import { piecesTool } from "./pieces";
import { postPreviewTool } from "./postpreview";
import { projectTool } from "./project";
import { resultsTool } from "./results";
import { scheduleTool } from "./schedule";
import { systemTool } from "./system";

/**
 * The hubs of the Tools list. Related panels are tabs of one panel, so a workspace needs few panels and nothing
 * stays empty beside an unselected list. Tab keys are stable: `show(wb, "evidence", { patch: { tab: "claims" } })`.
 */

export const projectHub = defineHub({
  id: "project",
  title: "Project",
  glyph: "◧",
  category: "Study",
  parts: [
    { key: "overview", title: "Overview", tool: projectTool },
    { key: "documents", title: "Documents", tool: documentsTool },
    { key: "check", title: "Check", tool: checkTool },
    { key: "agents", title: "Agents", tool: activityTool },
  ],
});

export const evidenceHub = defineHub({
  id: "evidence",
  title: "Evidence",
  glyph: "§",
  category: "Study",
  parts: [
    { key: "hypotheses", title: "Hypotheses", tool: hypothesesTool },
    { key: "claims", title: "Claims", tool: claimsTool },
    { key: "results", title: "Results", tool: resultsTool },
    { key: "reviews", title: "Reviews", tool: reviewsTool },
  ],
});

export const deliverableHub = defineHub({
  id: "deliverable",
  title: "Deliverable",
  glyph: "¶",
  category: "Study",
  parts: [
    { key: "read", title: "Read", tool: deliverableTool },
    { key: "all", title: "All and planned", tool: deliverablesTool },
  ],
});

export const piecesHub = defineHub({
  id: "pieces",
  title: "Pieces",
  glyph: "✉",
  category: "Pieces",
  side: { key: "list", title: "Pieces", tool: piecesTool },
  parts: [
    { key: "edit", title: "Text", tool: pieceTool },
    { key: "preview", title: "Post preview", tool: postPreviewTool },
    { key: "schedule", title: "Schedule", tool: scheduleTool },
  ],
});

export const sourcesHub = defineHub({
  id: "sources",
  title: "Sources",
  glyph: "⇄",
  category: "Data",
  parts: [
    { key: "connections", title: "Connections", tool: connectionsTool },
    { key: "jobs", title: "Jobs", tool: jobsTool },
    { key: "fetchlog", title: "Fetch log", tool: fetchLogTool },
  ],
});

export const systemHub = defineHub({
  id: "system",
  title: "System",
  glyph: "⚑",
  category: "System",
  parts: [
    { key: "overview", title: "Overview", tool: systemTool },
    { key: "assets", title: "Assets", tool: assetsTool },
  ],
});
