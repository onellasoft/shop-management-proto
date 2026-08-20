import React from 'react';
import { useApp } from '../context/AppContext';
import {
  Building2, Send, TrendingUp
} from 'lucide-react';
import { StatsCard, Card } from '../components/UI';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';

export const SuperAdminDashboard = () => {
  const { businesses, campaigns, setActivePath } = useApp();

  // Metrics Calculations
  const totalBusinesses = businesses.length;
  const activeBusinesses = businesses.filter(b => b.status === 'Active').length;
  const totalMessagesSent = businesses.reduce((acc, b) => acc + (b.usage?.messagesSent || 0), 0);

  // Charts Mock Data
  const growthData = [
    { name: 'Jan', stores: 5 },
    { name: 'Feb', stores: 12 },
    { name: 'Mar', stores: 20 },
    { name: 'Apr', stores: 28 },
    { name: 'May', stores: 40 },
    { name: 'Jun', stores: 50 },
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Super Admin Dashboard</h1>
          <p className="text-[12px] text-[#6B7280]">Real-time operational view of the Onella Shop SaaS platform.</p>
        </div>
        <div className="flex gap-2">
          <button
             onClick={() => setActivePath('businesses')}
            className="inline-flex items-center gap-1 text-xs font-semibold px-3 py-1.5 bg-white border border-[#E5E5E5] hover:bg-[#F5F5F5] rounded-custom transition-all"
          >
            Manage Businesses
          </button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard title="Total Stores" value={totalBusinesses} change="12%" trend="up" icon={Building2} />
        <StatsCard title="Active Stores" value={activeBusinesses} change="8%" trend="up" icon={Building2} />
        <StatsCard title="Total Messages" value={totalMessagesSent.toLocaleString()} change="24%" trend="up" icon={Send} />
        <StatsCard title="Campaigns Run" value={campaigns.length} change="5%" trend="up" icon={TrendingUp} />
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">

        {/* Business Growth Chart */}
        <Card title="Business Growth" subtitle="Cumulative storefront signups this half">
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={growthData} margin={{ left: -20, right: 10, top: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                <XAxis dataKey="name" stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111111', color: '#fff', borderRadius: '8px', border: 'none' }}
                  labelClassName="text-gray-400 font-bold"
                />
                <Line type="monotone" dataKey="stores" stroke="#111111" strokeWidth={2} dot={{ fill: '#111111', strokeWidth: 2 }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        {/* Message Delivery Stats */}
        <Card title="Message Volume" subtitle="Platform message distribution this half">
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={[
                { name: 'Jan', sent: 12000 },
                { name: 'Feb', sent: 19000 },
                { name: 'Mar', sent: 32000 },
                { name: 'Apr', sent: 48000 },
                { name: 'May', sent: 61000 },
                { name: 'Jun', sent: totalMessagesSent },
              ]} margin={{ left: -20, right: 10, top: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                <XAxis dataKey="name" stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#111111', color: '#fff', borderRadius: '8px', border: 'none' }}
                  labelClassName="text-gray-400 font-bold"
                />
                <Bar dataKey="sent" fill="#111111" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>

      </div>

      {/* Lower Section (Recent Businesses) */}
      <div className="bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-6">
        <div className="flex items-center justify-between pb-4 border-b border-[#F5F5F5] mb-4">
          <div>
            <h3 className="text-md font-semibold text-[#111111]">Recent Onboarded Businesses</h3>
            <p className="text-xs text-[#6B7280]">The latest tenants signing up on the platform.</p>
          </div>
          <button
            onClick={() => setActivePath('businesses')}
            className="text-xs font-semibold text-[#111111] hover:underline"
          >
            View all
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs divide-y divide-[#E5E5E5]">
            <thead>
              <tr className="text-gray-500 font-semibold uppercase">
                <th className="py-2.5">Store</th>
                <th className="py-2.5">Owner</th>
                <th className="py-2.5">Status</th>
                <th className="py-2.5">Joined Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F5F5F5] font-medium text-[#111111]">
              {businesses.slice(0, 5).map(biz => (
                <tr key={biz.id} className="hover:bg-[#FAFAFA]/50 transition-colors">
                  <td className="py-3 flex items-center gap-2">
                    <div className="h-7 w-7 rounded bg-[#111111] text-white font-bold flex items-center justify-center text-[10px]">
                      {biz.logo}
                    </div>
                    <span>{biz.name}</span>
                  </td>
                  <td className="py-3">{biz.owner}</td>
                  <td className="py-3">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] border ${biz.status === 'Active'
                      ? 'bg-[#E8F5E9] text-[#16A34A] border-[#C8E6C9]'
                      : 'bg-[#FFEBEE] text-[#DC2626] border-[#FFCDD2]'
                      }`}>
                      {biz.status}
                    </span>
                  </td>
                  <td className="py-3 text-gray-500">{biz.createdDate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
