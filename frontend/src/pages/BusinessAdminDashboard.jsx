import React from 'react';
import { useApp } from '../context/AppContext';
import { Users, Group, Send, FileText, CheckCircle2, TrendingUp, Clock, AlertTriangle } from 'lucide-react';
import { StatsCard, Card } from '../components/UI';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, LineChart, Line
} from 'recharts';

export const BusinessAdminDashboard = () => {
  const { contacts, groups, campaigns, templates, messages, setActivePath } = useApp();

  // Metrics
  const totalContacts = contacts.length;
  const activeGroups = groups.length;
  const totalTemplates = templates.length;
  const totalCampaigns = campaigns.length;

  const totalSent = messages.length;
  const readCount = messages.filter(m => m.status === 'Read').length;
  const deliveredCount = messages.filter(m => m.status === 'Delivered' || m.status === 'Read').length;
  const successRate = totalSent > 0 ? ((deliveredCount / totalSent) * 100).toFixed(1) : 100;

  // Chart Data
  const weeklyData = [
    { name: 'Mon', sent: 200, read: 140, failed: 5 },
    { name: 'Tue', sent: 450, read: 380, failed: 12 },
    { name: 'Wed', sent: 300, read: 260, failed: 4 },
    { name: 'Thu', sent: 700, read: 610, failed: 20 },
    { name: 'Fri', sent: 500, read: 410, failed: 8 },
    { name: 'Sat', sent: 150, read: 120, failed: 2 },
    { name: 'Sun', sent: 90, read: 75, failed: 1 }
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Business Admin Portal</h1>
          <p className="text-[12px] text-[#6B7280]">Campaign broadcast stats, contacts list segments, and channel status.</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setActivePath('campaigns')}
            className="inline-flex items-center gap-2 text-xs font-semibold px-4 py-2 bg-[#111111] text-white hover:bg-black/90 rounded-custom transition-all"
          >
            <Send className="h-3.5 w-3.5" />
            Launch Campaign
          </button>
        </div>
      </div>

      {/* Stats Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-6">
        <StatsCard title="Total Contacts" value={totalContacts} change="+24 this wk" trend="up" icon={Users} />
        <StatsCard title="Segments" value={activeGroups} change="Sync Ok" trend="neutral" icon={Group} />
        <StatsCard title="Templates" value={totalTemplates} change="3 Approved" trend="up" icon={FileText} />
        <StatsCard title="Campaigns Run" value={totalCampaigns} change="+2 new" trend="up" icon={TrendingUp} />
        <StatsCard title="Outgoing Broadcasts" value={totalSent} change="+12.4%" trend="up" icon={Send} />
        <StatsCard title="Delivery Success" value={`${successRate}%`} change="Optimal" trend="neutral" icon={CheckCircle2} />
      </div>

      {/* Recharts Analytics Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Weekly campaign bar chart */}
        <div className="lg:col-span-2">
          <Card title="Weekly Delivery Performance" subtitle="Comparison of messages sent, read, and delivery faults">
            <div className="h-64 mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={weeklyData} margin={{ left: -20, right: 10, top: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                  <XAxis dataKey="name" stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                  <YAxis stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#111111', color: '#fff', borderRadius: '8px', border: 'none' }}
                    labelClassName="text-gray-400 font-bold"
                  />
                  <Legend verticalAlign="top" height={36} iconType="circle" wrapperStyle={{ fontSize: '11px', fontWeight: 500 }} />
                  <Bar dataKey="sent" fill="#111111" name="Sent" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="read" fill="#9CA3AF" name="Read" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="failed" fill="#DC2626" name="Failed" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

        {/* Read Rate Gauge Simulator */}
        <Card title="Engagement Pipeline" subtitle="Overview of recipient action rates">
          <div className="space-y-6 mt-4">

            {/* Delivered Rate */}
            <div className="space-y-2">
              <div className="flex justify-between text-xs font-semibold">
                <span className="text-[#111111]">Delivered Rate</span>
                <span className="text-[#6B7280]">{(totalSent > 0 ? (messages.filter(m => m.status !== 'Failed').length / totalSent * 100) : 100).toFixed(0)}%</span>
              </div>
              <div className="w-full bg-[#FAFAFA] border border-[#E5E5E5] h-2 rounded-full overflow-hidden">
                <div className="bg-[#111111] h-full rounded-full" style={{ width: `${(totalSent > 0 ? (messages.filter(m => m.status !== 'Failed').length / totalSent * 100) : 100).toFixed(0)}%` }} />
              </div>
            </div>

            {/* Read Rate */}
            <div className="space-y-2 border-t border-[#F5F5F5] pt-4">
              <div className="flex justify-between text-xs font-semibold">
                <span className="text-[#111111]">Read / Open Rate</span>
                <span className="text-[#6B7280]">{(totalSent > 0 ? (readCount / totalSent * 100) : 100).toFixed(0)}%</span>
              </div>
              <div className="w-full bg-[#FAFAFA] border border-[#E5E5E5] h-2 rounded-full overflow-hidden">
                <div className="bg-[#9CA3AF] h-full rounded-full" style={{ width: `${(totalSent > 0 ? (readCount / totalSent * 100) : 100).toFixed(0)}%` }} />
              </div>
            </div>

            {/* Bounce Rate */}
            <div className="space-y-2 border-t border-[#F5F5F5] pt-4">
              <div className="flex justify-between text-xs font-semibold">
                <span className="text-[#111111]">Bounce / Failure Rate</span>
                <span className="text-[#6B7280]">{(totalSent > 0 ? (messages.filter(m => m.status === 'Failed').length / totalSent * 100) : 0).toFixed(0)}%</span>
              </div>
              <div className="w-full bg-[#FAFAFA] border border-[#E5E5E5] h-2 rounded-full overflow-hidden">
                <div className="bg-[#DC2626] h-full rounded-full" style={{ width: `${(totalSent > 0 ? (messages.filter(m => m.status === 'Failed').length / totalSent * 100) : 0).toFixed(0)}%` }} />
              </div>
            </div>

          </div>
        </Card>

      </div>

      {/* Lower Recent Campaign Status Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Recent Campaigns table */}
        <div className="lg:col-span-2 bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-6">
          <div className="flex items-center justify-between pb-4 border-b border-[#F5F5F5] mb-4">
            <div>
              <h3 className="text-md font-semibold text-[#111111]">Recent Campaign Logs</h3>
              <p className="text-xs text-[#6B7280]">Audit statuses of active and scheduled templates.</p>
            </div>
            <button
              onClick={() => setActivePath('campaigns')}
              className="text-xs font-semibold text-[#111111] hover:underline"
            >
              View all
            </button>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs divide-y divide-[#E5E5E5]">
              <thead>
                <tr className="text-gray-500 font-semibold uppercase">
                  <th className="py-2.5">Campaign</th>
                  <th className="py-2.5">Template</th>
                  <th className="py-2.5">Sent</th>
                  <th className="py-2.5">Delivered</th>
                  <th className="py-2.5">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F5F5F5] font-medium text-[#111111]">
                {campaigns.slice(0, 5).map(camp => (
                  <tr key={camp.id} className="hover:bg-[#FAFAFA]/50 transition-colors">
                    <td className="py-3 font-semibold text-[#111111]">{camp.name}</td>
                    <td className="py-3 font-mono text-gray-500">{camp.template}</td>
                    <td className="py-3">{camp.sentCount}</td>
                    <td className="py-3">{camp.delivered}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] border ${camp.status === 'Completed'
                        ? 'bg-[#E8F5E9] text-[#16A34A] border-[#C8E6C9]'
                        : camp.status === 'Active'
                          ? 'bg-[#E0F2FE] text-[#0284C7] border-[#BAE6FD]'
                          : camp.status === 'Scheduled'
                            ? 'bg-[#FFF3E0] text-[#D97706] border-[#FFE0B2]'
                            : 'bg-[#FAFAFA] text-[#6B7280] border-[#E5E5E5]'
                        }`}>
                        {camp.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Message Log list */}
        <Card title="Live Message Log" subtitle="Real-time delivery status feed">
          <div className="space-y-4 max-h-72 overflow-y-auto no-scrollbar pr-1">
            {messages.slice(0, 5).map(msg => (
              <div key={msg.id} className="flex justify-between items-start border-b border-[#F5F5F5] pb-3 last:border-0 last:pb-0">
                <div className="space-y-0.5">
                  <p className="text-xs font-semibold text-[#111111]">{msg.contactName}</p>
                  <p className="text-[10px] text-[#6B7280]">Tpl: {msg.templateName}</p>
                </div>
                <div className="text-right space-y-0.5">
                  <span className={`inline-block px-1.5 py-0.2 rounded-full text-[9px] font-bold border ${msg.status === 'Read' ? 'bg-[#E8F5E9] text-[#16A34A] border-[#C8E6C9]' :
                    msg.status === 'Delivered' ? 'bg-[#E0F2FE] text-[#0284C7] border-[#BAE6FD]' :
                      msg.status === 'Failed' ? 'bg-[#FFEBEE] text-[#DC2626] border-[#FFCDD2]' :
                        'bg-[#FAFAFA] text-[#6B7280] border-[#E5E5E5]'
                    }`}>
                    {msg.status}
                  </span>
                  <p className="text-[9px] text-[#6B7280]">{msg.timestamp}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>

      </div>
    </div>
  );
};
