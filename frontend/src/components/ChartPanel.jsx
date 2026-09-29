import { useState } from 'react';
import { motion } from 'framer-motion';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';

export default function ChartPanel({ result, chart_type = 'none' }) {
  const [activeTab, setActiveTab] = useState(chart_type === 'none' ? 'table' : 'chart');

  // Handle null / empty result
  if (!result || !Array.isArray(result) || result.length === 0) {
    return (
      <div className="w-full my-2.5 p-6 rounded-2xl bg-white/70 backdrop-blur-sm border border-slate-200/70 text-center text-slate-500 text-sm italic shadow-2xs">
        📊 No data returned
      </div>
    );
  }

  const keys = Object.keys(result[0] || {});
  if (keys.length === 0) {
    return (
      <div className="w-full my-2.5 p-6 rounded-2xl bg-white/70 backdrop-blur-sm border border-slate-200/70 text-center text-slate-500 text-sm italic shadow-2xs">
        No columns present in result
      </div>
    );
  }

  // Dynamically inspect first row to find X (category) and Y (numeric) keys
  const xKey = keys.find((k) => typeof result[0][k] === 'string') || keys[0];
  const yKey = keys.find((k) => typeof result[0][k] === 'number') || keys[1] || keys[0];

  const hasChart = chart_type === 'bar' || chart_type === 'line';

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.2 }}
      className="w-full my-2 bg-white/80 backdrop-blur-md border border-slate-200/70 rounded-2xl p-4 shadow-sm transition-colors duration-200"
    >
      {/* View Switcher Header */}
      <div className="flex items-center justify-between mb-3 pb-2 border-b border-slate-100">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-600 flex items-center gap-1.5">
          <span>📊</span> Result Data ({result.length} {result.length === 1 ? 'row' : 'rows'})
        </span>

        {hasChart && (
          <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl text-xs">
            <button
              onClick={() => setActiveTab('chart')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                activeTab === 'chart'
                  ? 'bg-white text-teal-700 shadow-2xs font-semibold'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Chart ({chart_type})
            </button>
            <button
              onClick={() => setActiveTab('table')}
              className={`px-3 py-1 rounded-lg font-medium transition-all ${
                activeTab === 'table'
                  ? 'bg-white text-teal-700 shadow-2xs font-semibold'
                  : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Table View
            </button>
          </div>
        )}
      </div>

      {/* Render Chart View */}
      {hasChart && activeTab === 'chart' ? (
        <div className="w-full h-64 pt-2">
          <ResponsiveContainer width="100%" height="100%">
            {chart_type === 'bar' ? (
              <BarChart data={result} margin={{ top: 10, right: 10, left: -10, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#CBD5E1" opacity={0.4} />
                <XAxis dataKey={xKey} stroke="#64748B" tick={{ fontSize: 12 }} />
                <YAxis stroke="#64748B" tick={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#FFFFFF',
                    borderColor: '#E2E8F0',
                    color: '#0F172A',
                    borderRadius: '0.75rem',
                    boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
                    fontSize: '12px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                <Bar dataKey={yKey} fill="#028090" radius={[6, 6, 0, 0]} name={yKey} />
              </BarChart>
            ) : (
              <LineChart data={result} margin={{ top: 10, right: 10, left: -10, bottom: 20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#CBD5E1" opacity={0.4} />
                <XAxis dataKey={xKey} stroke="#64748B" tick={{ fontSize: 12 }} />
                <YAxis stroke="#64748B" tick={{ fontSize: 12 }} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#FFFFFF',
                    borderColor: '#E2E8F0',
                    color: '#0F172A',
                    borderRadius: '0.75rem',
                    boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)',
                    fontSize: '12px',
                  }}
                />
                <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                <Line type="monotone" dataKey={yKey} stroke="#028090" strokeWidth={2.5} dot={{ r: 4, fill: '#028090' }} name={yKey} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
      ) : (
        /* Render Clean Light HTML Table */
        <div className="overflow-x-auto rounded-xl border border-slate-200/80 shadow-2xs">
          <table className="w-full text-xs sm:text-sm text-left text-slate-700">
            <thead className="bg-slate-50 text-slate-800 uppercase font-mono text-[11px] tracking-wider border-b border-slate-200">
              <tr>
                {keys.map((k) => (
                  <th key={k} className="px-3.5 py-2.5 font-semibold">{k}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white/70">
              {result.map((row, rowIdx) => (
                <tr key={rowIdx} className="hover:bg-teal-50/40 transition-colors">
                  {keys.map((k) => (
                    <td key={k} className="px-3.5 py-2.5 whitespace-nowrap font-mono text-xs">
                      {String(row[k] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

    </motion.div>
  );
}
