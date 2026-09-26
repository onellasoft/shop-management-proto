import React, { useMemo } from 'react';
import { useApp } from '../context/AppContext';
import { Building2, CheckCircle2, PauseCircle, Send, TrendingUp } from 'lucide-react';
import { StatsCard, Card } from '../components/UI';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line
} from 'recharts';

/**
 * AgencyAdminDashboard — an agency-scoped overview. Shows metrics and recent
 * activity for the businesses (customers) that belong to THIS agency only,
 * derived from the logged-in agencyadmin's agency_id.
 */
export const AgencyAdminDashboard = () => {
  const { businesses, agencies, userInfo, setActivePath } = useApp();

  // Scope everything to the agency this admin belongs to.
  const agencyId = userInfo?.agency_id ?? agencies[0]?.id ?? null;
  const agency = agencies.find(a => a.id === agencyId);

  const myBusinesses = useMemo(
    () => businesses.filter(b => b.agencyId === agencyId),
    [businesses, agencyId]
  );

  const totalBusinesses = myBusinesses.length;
  const activeBusinesses = myBusinesses.filter(b => b.status === 'Active').length;
  const suspendedBusinesses = myBusinesses.filter(b => b.status === 'Suspended').length;
  const totalMessages = myBusinesses.reduce((acc, b) => acc + (b.usage?.messagesSent || 0), 0);

  const growthData = [
    { name: 'Jan', businesses: Math.round(totalBusinesses * 0.2) },
    { name: 'Feb', businesses: Math.round(totalBusinesses * 0.4) },
    { name: 'Mar', businesses: Math.round(totalBusinesses * 0.6) },
    { name: 'Apr', businesses: Math.round(totalBusinesses * 0.75) },
    { name: 'May', businesses: Math.round(totalBusinesses * 0.9) },
    { name: 'Jun', businesses: totalBusinesses },
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">
            {agency ? `${agency.name} — Agency Dashboard` : 'Agency Dashboard'}
          </h1>
          <p className="text-[12px] text-[#6B7280]">Overview of the businesses you manage under your agency.</p>
        </div>
        <button
          onClick={() => setActivePath('businesses')}
          className="inline-flex items-center gap-2 text-xs font-semibold px-4 py-2 bg-[#111111] text-white hover:bg-black/90 rounded-custom transition-all"
        >
          <Building2 className="h-3.5 w-3.5" />
          Manage Businesses
        </button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard title="My Businesses" value={totalBusinesses} change="Total" trend="neutral" icon={Building2} />
        <StatsCard title="Active" value={activeBusinesses} change="Live" trend="up" icon={CheckCircle2} />
        <StatsCard title="Suspended" value={suspendedBusinesses} change="On hold" trend="neutral" icon={PauseCircle} />
        <StatsCard title="Messages Sent" value={totalMessages.toLocaleString()} change="All time" trend="up" icon={Send} />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <Card title="Business Growth" subtitle="Cumulative businesses onboarded under your agency">
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={growthData} margin={{ left: -20, right: 10, top: 10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                <XAxis dataKey="name" stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#111111', color: '#fff', borderRadius: '8px', border: 'none' }} />
                <Line type="monotone" dataKey="businesses" stroke="#111111" strokeWidth={2} dot={{ fill: '#111111', strokeWidth: 2 }} activeDot={{ r: 6 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Message Volume" subtitle="Messages sent across your businesses">
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={[
                  { name: 'Jan', sent: Math.round(totalMessages * 0.1) },
                  { name: 'Feb', sent: Math.round(totalMessages * 0.25) },
                  { name: 'Mar', sent: Math.round(totalMessages * 0.45) },
                  { name: 'Apr', sent: Math.round(totalMessages * 0.65) },
                  { name: 'May', sent: Math.round(totalMessages * 0.85) },
                  { name: 'Jun', sent: totalMessages },
                ]}
                margin={{ left: -20, right: 10, top: 10, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                <XAxis dataKey="name" stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <YAxis stroke="#9CA3AF" fontSize={12} tickLine={false} axisLine={false} />
                <Tooltip contentStyle={{ backgroundColor: '#111111', color: '#fff', borderRadius: '8px', border: 'none' }} />
                <Bar dataKey="sent" fill="#111111" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      {/* Recent businesses under this agency */}
      <div className="bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-6">
        <div className="flex items-center justify-between pb-4 border-b border-[#F5F5F5] mb-4">
          <div>
            <h3 className="text-md font-semibold text-[#111111]">Your Businesses</h3>
            <p className="text-xs text-[#6B7280]">Businesses onboarded under your agency.</p>
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
                <th className="py-2.5">Business</th>
                <th className="py-2.5">Owner</th>
                <th className="py-2.5">Status</th>
                <th className="py-2.5">Joined Date</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F5F5F5] font-medium text-[#111111]">
              {myBusinesses.length > 0 ? (
                myBusinesses.slice(0, 5).map(biz => (
                  <tr key={biz.id} className="hover:bg-[#FAFAFA]/50 transition-colors">
                    <td className="py-3 flex items-center gap-2">
                      <div className="h-7 w-7 rounded bg-[#111111] text-white font-bold flex items-center justify-center text-[10px]">
                        {biz.logo}
                      </div>
                      <span>{biz.name}</span>
                    </td>
                    <td className="py-3">{biz.owner}</td>
                    <td className="py-3">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] border ${
                        biz.status === 'Active'
                          ? 'bg-[#E8F5E9] text-[#16A34A] border-[#C8E6C9]'
                          : 'bg-[#FFEBEE] text-[#DC2626] border-[#FFCDD2]'
                      }`}>
                        {biz.status}
                      </span>
                    </td>
                    <td className="py-3 text-gray-500">{biz.createdDate}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={4} className="py-8 text-center text-[#6B7280]">
                    No businesses yet. Add one from Business Management.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
