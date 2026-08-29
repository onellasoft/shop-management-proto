import React from 'react';
import { useApp } from '../context/AppContext';
import { Card, Button, StatsCard, Badge } from '../components/UI';
import { ArrowLeft, MessageSquare, CheckCircle, Eye, AlertTriangle } from 'lucide-react';
import {
  PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid
} from 'recharts';

export const CampaignReport = ({ campaignId, onClose }) => {
  const { campaigns, messages } = useApp();

  const campaign = campaigns.find(c => c.id === campaignId);

  if (!campaign) {
    return (
      <div className="text-center py-12">
        <p className="text-[12px] text-[#6B7280]">Campaign report not found.</p>
        <Button variant="secondary" className="mt-4" onClick={onClose}>Go Back</Button>
      </div>
    );
  }

  // Calculate percentages
  const deliveredPercent = campaign.sentCount > 0 ? ((campaign.delivered / campaign.sentCount) * 100).toFixed(0) : 0;
  const readPercent = campaign.delivered > 0 ? ((campaign.read / campaign.delivered) * 100).toFixed(0) : 0;
  const failedPercent = campaign.sentCount > 0 ? ((campaign.failed / campaign.sentCount) * 100).toFixed(0) : 0;

  // Chart Data
  const chartData = [
    { name: 'Read', value: campaign.read },
    { name: 'Delivered (Unread)', value: campaign.delivered - campaign.read },
    { name: 'Failed', value: campaign.failed }
  ];

  const COLORS = ['#111111', '#9CA3AF', '#DC2626'];

  const timelineData = [
    { hour: '10:00 AM', sent: Math.floor(campaign.sentCount * 0.2), read: Math.floor(campaign.read * 0.15) },
    { hour: '10:15 AM', sent: Math.floor(campaign.sentCount * 0.5), read: Math.floor(campaign.read * 0.4) },
    { hour: '10:30 AM', sent: Math.floor(campaign.sentCount * 0.8), read: Math.floor(campaign.read * 0.7) },
    { hour: '10:45 AM', sent: campaign.sentCount, read: campaign.read }
  ];

  // Filter messages generated during this campaign (simulated lookup)
  const campaignMessages = messages
    .filter(m => m.templateName === campaign.template)
    .slice(0, 10);

  return (
    <div className="space-y-8">
      {/* Back Header */}
      <div className="flex items-center gap-4">
        <Button variant="secondary" size="sm" onClick={onClose} className="p-2">
          <ArrowLeft className="h-4 w-4 text-[#111111]" />
        </Button>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-[28px] font-bold text-[#111111] tracking-tight">{campaign.name}</h1>
            <Badge variant="success">Completed</Badge>
          </div>
          <p className="text-xs text-[#6B7280]">Template: #{campaign.template} • Dispatched to {campaign.group}</p>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <StatsCard title="Total Dispatched" value={campaign.sentCount} icon={MessageSquare} />
        <StatsCard title="Delivered Rate" value={`${deliveredPercent}%`} change={`${campaign.delivered} msgs`} trend="up" icon={CheckCircle} />
        <StatsCard title="Read Rate" value={`${readPercent}%`} change={`${campaign.read} msgs`} trend="up" icon={Eye} />
        <StatsCard title="Failure Rate" value={`${failedPercent}%`} change={`${campaign.failed} msgs`} trend={campaign.failed > 0 ? "down" : "neutral"} icon={AlertTriangle} />
      </div>

      {/* Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Pie distribution */}
        <Card title="Recipients Distribution" subtitle="Deliverability percentages">
          <div className="h-64 mt-2 flex flex-col justify-between">
            <div className="h-[75%] relative">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={chartData}
                    cx="50%"
                    cy="50%"
                    innerRadius={50}
                    outerRadius={70}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ backgroundColor: '#111111', color: '#fff', borderRadius: '8px', border: 'none' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>

            <div className="flex justify-center gap-6 text-xs font-semibold text-[#6B7280]">
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#111111]" />
                <span>Read ({campaign.read})</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#9CA3AF]" />
                <span>Unread ({campaign.delivered - campaign.read})</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="w-2.5 h-2.5 rounded-full bg-[#DC2626]" />
                <span>Failed ({campaign.failed})</span>
              </div>
            </div>
          </div>
        </Card>

        {/* Timeline */}
        <div className="lg:col-span-2">
          <Card title="Broadcast Send Speed" subtitle="Total dispatches logged over time">
            <div className="h-64 mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={timelineData} margin={{ left: -20, right: 10, top: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                  <XAxis dataKey="hour" stroke="#9CA3AF" fontSize={11} tickLine={false} axisLine={false} />
                  <YAxis stroke="#9CA3AF" fontSize={11} tickLine={false} axisLine={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#111111', color: '#fff', borderRadius: '8px', border: 'none' }}
                    labelClassName="text-gray-400 font-bold"
                  />
                  <Bar dataKey="sent" fill="#111111" name="Dispatched" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="read" fill="#9CA3AF" name="Read" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
        </div>

      </div>

      {/* Recipient Log Table Summary */}
      <div className="bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-6">
        <div className="pb-4 border-b border-[#F5F5F5] mb-4">
          <h3 className="text-md font-semibold text-[#111111]">Recipients Audit Table</h3>
          <p className="text-xs text-[#6B7280]">Individual log lines dispatched in this campaign.</p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs divide-y divide-[#E5E5E5]">
            <thead>
              <tr className="text-gray-500 font-semibold uppercase">
                <th className="py-2.5">Name</th>
                <th className="py-2.5">Mobile</th>
                <th className="py-2.5">Status</th>
                <th className="py-2.5">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F5F5F5] font-medium text-[#111111]">
              {campaignMessages.map(msg => (
                <tr key={msg.id} className="hover:bg-[#FAFAFA]/50 transition-colors">
                  <td className="py-3 font-semibold text-[#111111]">{msg.contactName}</td>
                  <td className="py-3 font-mono text-gray-500">{msg.mobile}</td>
                  <td className="py-3">
                    <Badge variant={msg.status === 'Read' ? 'success' : msg.status === 'Delivered' ? 'neutral' : 'danger'}>
                      {msg.status}
                    </Badge>
                  </td>
                  <td className="py-3 text-gray-500">{msg.timestamp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
};
