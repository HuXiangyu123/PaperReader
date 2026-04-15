import {
  getGraphNodes,
  getNodeLabel,
  getWorkflowMode,
  type AnyNodeName,
  type NodeStatus,
  type SourceType,
} from '../types/task';

interface Props {
  nodeStatuses: Record<AnyNodeName, NodeStatus>;
  sourceType?: SourceType | null;
  currentStage?: string | null;
}

export function ProgressBar({ nodeStatuses, sourceType, currentStage }: Props) {
  const graphNodes = getGraphNodes(sourceType);
  const workflowMode = getWorkflowMode(sourceType);
  const done = graphNodes.filter(node => nodeStatuses[node] === 'done').length;
  const pct = Math.round((done / graphNodes.length) * 100);
  const running = graphNodes.find(node => nodeStatuses[node] === 'running');
  const stageLabel = running
    ? `Running: ${getNodeLabel(running)}`
    : currentStage
      ? `Latest: ${getNodeLabel(currentStage)}`
      : done === graphNodes.length
        ? 'Complete'
        : 'Idle';

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3 text-xs text-stone-600">
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-white/80 px-2.5 py-1 font-medium text-stone-700 border border-stone-300/70">
            {workflowMode === 'research' ? 'Research Workflow' : 'Report Workflow'}
          </span>
          <span className="font-medium">{stageLabel}</span>
        </div>
        <span className="tabular-nums text-stone-500">
          {done}/{graphNodes.length} nodes ({pct}%)
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full border border-stone-300/80 bg-stone-200">
        <div
          className="h-full rounded-full bg-[#1e3a5f] transition-all duration-300"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
