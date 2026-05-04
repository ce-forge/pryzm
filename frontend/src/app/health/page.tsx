"use client";

import { useEffect, useState } from "react";
import { Activity, Database, Server, BrainCircuit, Network, AlertTriangle, CheckCircle2 } from "lucide-react";

interface SystemStatus {
  api: string;
  redis: string;
  database: string;
  inference_engine: string;
}

interface HealthData {
  status: string;
  components: SystemStatus;
}

export default function SystemHealth() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>("");

  const fetchHealth = async () => {
    try {
      const res = await fetch("http://localhost:8000/health");
      const data = await res.json();
      setHealth(data);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (error) {
      console.error("Failed to fetch telemetry", error);
    }
  };

  useEffect(() => {
    fetchHealth();
    // Auto-refresh the dashboard every 10 seconds
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  // Helper function to colorize status
  const getStatusColor = (status: string | undefined) => {
    if (status === "connected" || status === "healthy" || status === "online") return "text-emerald-400 bg-emerald-400/10 border border-emerald-400/20";
    if (status === "degraded") return "text-amber-400 bg-amber-400/10 border border-amber-400/20";
    return "text-rose-400 bg-rose-400/10 border border-rose-400/20";
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      
      {/* Header */}
      <div className="flex justify-between items-end mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-100">System Telemetry</h1>
          <p className="text-sm text-slate-400 mt-1">Live infrastructure and remote node routing status</p>
        </div>
        <div className="text-xs font-mono text-slate-500 flex items-center gap-2">
          <Activity size={14} className="animate-pulse text-emerald-500" />
          Last sync: {lastUpdated || "fetching..."}
        </div>
      </div>

      {/* Top Row: Core Infrastructure */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-slate-800/50 border border-slate-700 p-5 rounded-xl flex flex-col justify-between">
          <div className="flex items-center gap-3 text-slate-400 mb-4">
            <Server size={20} />
            <h3 className="font-semibold text-sm">API Gateway</h3>
          </div>
          <div className={`px-3 py-1.5 rounded-md w-fit text-xs font-mono uppercase tracking-wider ${getStatusColor(health?.components.api)}`}>
            {health?.components.api || "OFFLINE"}
          </div>
        </div>

        <div className="bg-slate-800/50 border border-slate-700 p-5 rounded-xl flex flex-col justify-between">
          <div className="flex items-center gap-3 text-slate-400 mb-4">
            <Database size={20} />
            <h3 className="font-semibold text-sm">PostgreSQL Vault</h3>
          </div>
          <div className={`px-3 py-1.5 rounded-md w-fit text-xs font-mono uppercase tracking-wider ${getStatusColor(health?.components.database)}`}>
            {health?.components.database || "OFFLINE"}
          </div>
        </div>

        <div className="bg-slate-800/50 border border-slate-700 p-5 rounded-xl flex flex-col justify-between">
          <div className="flex items-center gap-3 text-slate-400 mb-4">
            <Network size={20} />
            <h3 className="font-semibold text-sm">Redis Broker</h3>
          </div>
          <div className={`px-3 py-1.5 rounded-md w-fit text-xs font-mono uppercase tracking-wider ${getStatusColor(health?.components.redis)}`}>
            {health?.components.redis || "OFFLINE"}
          </div>
        </div>

        <div className="bg-slate-800/50 border border-slate-700 p-5 rounded-xl flex flex-col justify-between">
          <div className="flex items-center gap-3 text-slate-400 mb-4">
            <BrainCircuit size={20} />
            <h3 className="font-semibold text-sm">Inference Engine</h3>
          </div>
          <div className={`px-3 py-1.5 rounded-md w-fit text-xs font-mono uppercase tracking-wider ${getStatusColor(health?.components.inference_engine)}`}>
            {health?.components.inference_engine || "OFFLINE"}
          </div>
        </div>
      </div>

      {/* Bottom Row: Active Operations */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 pt-4">
        
        {/* Active Nodes */}
        <div className="lg:col-span-2 bg-slate-800/50 border border-slate-700 rounded-xl overflow-hidden">
          <div className="p-5 border-b border-slate-700 bg-slate-800/80">
            <h3 className="font-semibold text-slate-200">Active Remediation Targets</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left text-slate-400">
              <thead className="text-xs uppercase bg-slate-900/50 border-b border-slate-700 text-slate-500">
                <tr>
                  <th className="px-5 py-3">Node Hostname</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Current Action</th>
                  <th className="px-5 py-3 text-right">Ping</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/50">
                <tr className="hover:bg-slate-800/50 transition-colors">
                  <td className="px-5 py-4 font-mono text-slate-300">WS-HQ-042</td>
                  <td className="px-5 py-4"><span className="text-emerald-400 flex items-center gap-1"><CheckCircle2 size={14}/> Active</span></td>
                  <td className="px-5 py-4">Awaiting execution payload</td>
                  <td className="px-5 py-4 text-right font-mono">12ms</td>
                </tr>
                <tr className="hover:bg-slate-800/50 transition-colors">
                  <td className="px-5 py-4 font-mono text-slate-300">SRV-DB-01</td>
                  <td className="px-5 py-4"><span className="text-amber-400 flex items-center gap-1"><AlertTriangle size={14}/> Warning</span></td>
                  <td className="px-5 py-4">Analyzing thermal log anomalies</td>
                  <td className="px-5 py-4 text-right font-mono">45ms</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Audit Log */}
        <div className="bg-slate-800/50 border border-slate-700 rounded-xl flex flex-col">
          <div className="p-5 border-b border-slate-700 bg-slate-800/80">
            <h3 className="font-semibold text-slate-200">Recent API Handshakes</h3>
          </div>
          <div className="p-5 space-y-4 flex-1">
            <div className="border-l-2 border-emerald-500 pl-3">
              <p className="text-xs text-slate-500 font-mono mb-1">10:42:05 AM</p>
              <p className="text-sm text-slate-300">Inference request routed to GPU</p>
            </div>
            <div className="border-l-2 border-emerald-500 pl-3">
              <p className="text-xs text-slate-500 font-mono mb-1">10:41:12 AM</p>
              <p className="text-sm text-slate-300">System health global refresh</p>
            </div>
            <div className="border-l-2 border-amber-500 pl-3">
              <p className="text-xs text-slate-500 font-mono mb-1">10:35:00 AM</p>
              <p className="text-sm text-slate-300">CORS Preflight bypassed</p>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}