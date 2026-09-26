import React, { useState, useMemo } from 'react';
import { useApp } from '../context/AppContext';
import { DataTable } from '../components/DataTable';
import { Button, Input } from '../components/UI';
import { Modal, ConfirmDialog } from '../components/Modal';
import { FiPlus, FiBriefcase } from 'react-icons/fi';

/**
 * AgencyManagement — superadmin-only view to see, add, and manage all agencies
 * on the platform. Mirrors the businesses management pattern but scoped to the
 * agency entity (an agency owns many businesses/customers).
 */
export const AgencyManagement = () => {
  const { agencies, businesses, addAgency, suspendAgency } = useApp();

  const [statusFilter, setStatusFilter] = useState('All');
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [newAgency, setNewAgency] = useState({ name: '', owner: '', email: '', mobile: '' });
  const [confirmStatus, setConfirmStatus] = useState({ isOpen: false, id: null, name: '', isSuspended: false });

  // Count of businesses per agency, so the superadmin sees agency size at a glance.
  const bizCountByAgency = useMemo(() => {
    return businesses.reduce((acc, b) => {
      if (!b.agencyId) return acc;
      acc[b.agencyId] = (acc[b.agencyId] || 0) + 1;
      return acc;
    }, {});
  }, [businesses]);

  const filteredData = useMemo(
    () => agencies.filter(a => statusFilter === 'All' || a.status === statusFilter),
    [agencies, statusFilter]
  );

  const handleCreate = (e) => {
    e.preventDefault();
    if (!newAgency.name.trim()) return;
    addAgency(newAgency);
    setNewAgency({ name: '', owner: '', email: '', mobile: '' });
    setIsCreateOpen(false);
  };

  const columns = [
    {
      key: 'name',
      title: 'Agency',
      sortable: true,
      render: (val, row) => (
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-[#111111] text-white font-bold flex items-center justify-center text-xs font-mono circle-avatar">
            {row.logo}
          </div>
          <div>
            <div className="font-semibold text-[#111111]">{val}</div>
            <div className="text-[11px] text-[#6B7280]">ID: {row.id}</div>
          </div>
        </div>
      ),
    },
    { key: 'owner', title: 'Owner', sortable: true },
    {
      key: 'mobile',
      title: 'Contact',
      render: (val, row) => (
        <div>
          <div>{val}</div>
          <div className="text-[11px] text-[#6B7280]">{row.email}</div>
        </div>
      ),
    },
    {
      key: 'businesses',
      title: 'Businesses',
      render: (_, row) => (
        <span className="font-semibold text-[#111111]">{bizCountByAgency[row.id] || 0}</span>
      ),
    },
    {
      key: 'status',
      title: 'Status',
      sortable: true,
      render: (val, row) => {
        const isSuspended = val === 'Suspended';
        return (
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <label className="relative inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                className="sr-only peer"
                checked={!isSuspended}
                onChange={() => setConfirmStatus({ isOpen: true, id: row.id, name: row.name, isSuspended })}
              />
              <div className="custom-toggle w-8 h-4 bg-[#D97706] rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[4px] after:bg-[#FEF3C7] after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-[#111111] peer-checked:after:bg-white transition-all"></div>
            </label>
            <span className="text-[12px] font-medium text-[#111111]">{val}</span>
          </div>
        );
      },
    },
  ];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Agency Management</h1>
          <p className="text-[12px] text-[#6B7280]">See, onboard, and manage every agency on the platform.</p>
        </div>
        <Button variant="primary" icon={FiPlus} onClick={() => setIsCreateOpen(true)}>
          Add Agency
        </Button>
      </div>

      {/* Status filter */}
      <div className="flex items-center gap-2">
        {['All', 'Active', 'Suspended'].map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 text-xs font-semibold rounded-custom transition-all ${
              statusFilter === s
                ? 'bg-[#111111] text-white'
                : 'bg-white border border-[#E5E5E5] text-[#6B7280] hover:text-[#111111]'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      <DataTable
        columns={columns}
        data={filteredData}
        searchKey="name"
        searchPlaceholder="Search agencies by name..."
        emptyState={
          <div className="py-12 text-center text-[#6B7280]">
            <FiBriefcase className="h-8 w-8 mx-auto mb-3 opacity-40" />
            <p className="text-sm font-semibold text-[#111111]">No agencies found</p>
            <p className="text-xs mt-1">Add your first agency to get started.</p>
          </div>
        }
      />

      {/* Create Agency Modal */}
      <Modal isOpen={isCreateOpen} onClose={() => setIsCreateOpen(false)} title="Add New Agency">
        <form onSubmit={handleCreate} className="space-y-4">
          <Input
            label="Agency Name"
            value={newAgency.name}
            onChange={e => setNewAgency({ ...newAgency, name: e.target.value })}
            placeholder="e.g. Bright Retail Group"
            required
          />
          <Input
            label="Owner Name"
            value={newAgency.owner}
            onChange={e => setNewAgency({ ...newAgency, owner: e.target.value })}
            placeholder="e.g. Nikhil Verma"
          />
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Email"
              type="email"
              value={newAgency.email}
              onChange={e => setNewAgency({ ...newAgency, email: e.target.value })}
              placeholder="contact@agency.com"
            />
            <Input
              label="Mobile"
              value={newAgency.mobile}
              onChange={e => setNewAgency({ ...newAgency, mobile: e.target.value })}
              placeholder="+91 98765 43210"
            />
          </div>
          <div className="pt-2 flex justify-end gap-2">
            <Button variant="secondary" type="button" onClick={() => setIsCreateOpen(false)}>Cancel</Button>
            <Button variant="primary" type="submit">Create Agency</Button>
          </div>
        </form>
      </Modal>

      {/* Suspend / Activate confirm */}
      <ConfirmDialog
        isOpen={confirmStatus.isOpen}
        onClose={() => setConfirmStatus({ ...confirmStatus, isOpen: false })}
        onConfirm={() => {
          suspendAgency(confirmStatus.id);
          setConfirmStatus({ ...confirmStatus, isOpen: false });
        }}
        title={confirmStatus.isSuspended ? 'Activate Agency' : 'Suspend Agency'}
        message={`Are you sure you want to ${confirmStatus.isSuspended ? 'activate' : 'suspend'} "${confirmStatus.name}"?`}
        confirmText={confirmStatus.isSuspended ? 'Activate' : 'Suspend'}
      />
    </div>
  );
};
