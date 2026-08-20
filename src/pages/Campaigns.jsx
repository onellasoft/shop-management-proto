import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { DataTable } from '../components/DataTable';
import { Badge, Button, Input } from '../components/UI';
import { Modal } from '../components/Modal';
import { Plus, Send, PhoneCall, BarChart3, Clock, PlayCircle } from 'lucide-react';
import { CampaignReport } from './CampaignReport';

export const Campaigns = () => {
  const { campaigns, templates, groups, whatsappNumbers, startCampaign } = useApp();
  const [selectedCampId, setSelectedCampId] = useState(null);

  // Modal & Form State
  const [isLaunchModalOpen, setIsLaunchModalOpen] = useState(false);
  const [isTestModalOpen, setIsTestModalOpen] = useState(false);
  const [testNumber, setTestNumber] = useState('');

  const [newCampaign, setNewCampaign] = useState({
    name: '',
    template: '',
    group: '',
    whatsappNumber: '',
    schedule: 'Immediate',
    scheduledTime: ''
  });

  // Filter templates to show only approved ones
  const approvedTemplates = templates.filter(t => t.status === 'Approved');

  const handleLaunchSubmit = (e) => {
    e.preventDefault();
    if (!newCampaign.name || !newCampaign.template || !newCampaign.group) return;

    startCampaign(newCampaign);
    setIsLaunchModalOpen(false);
    setNewCampaign({
      name: '', template: '', group: '', whatsappNumber: '', schedule: 'Immediate', scheduledTime: ''
    });
  };

  const handleTestSend = (e) => {
    e.preventDefault();
    if (!testNumber) return;
    alert(`Mock Verification: Test message dispatched to ${testNumber}!`);
    setIsTestModalOpen(false);
    setTestNumber('');
  };

  // If a campaign report is clicked, render the report component
  if (selectedCampId) {
    return <CampaignReport campaignId={selectedCampId} onClose={() => setSelectedCampId(null)} />;
  }

  const columns = [
    {
      key: 'name',
      title: 'Campaign Name',
      sortable: true,
      render: (val) => <span className="font-semibold text-[#111111]">{val}</span>
    },
    {
      key: 'template',
      title: 'WhatsApp Template',
      sortable: true,
      render: (val) => <span className="font-mono text-xs text-[#6B7280]">#{val}</span>
    },
    {
      key: 'group',
      title: 'Audience Group',
      sortable: true,
    },
    {
      key: 'sentCount',
      title: 'Recipients',
      sortable: true,
      render: (val, row) => (
        <div>
          <span className="font-semibold">{val}</span>
          {row.status === 'Completed' && (
            <span className="text-[10px] text-[#6B7280] ml-1">({row.delivered} del)</span>
          )}
        </div>
      )
    },
    {
      key: 'status',
      title: 'Status',
      sortable: true,
      render: (val) => {
        const variants = {
          'Completed': 'success',
          'Active': 'primary',
          'Scheduled': 'warning',
          'Draft': 'neutral'
        };
        return <Badge variant={variants[val]}>{val}</Badge>;
      }
    },
    {
      key: 'scheduledDate',
      title: 'Scheduled Date',
      sortable: true,
      className: 'text-xs text-[#6B7280]'
    },
    {
      key: 'actions',
      title: 'Actions',
      render: (_, row) => (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {row.status === 'Completed' && (
            <Button
              variant="secondary"
              size="sm"
              className="p-1.5"
              title="View Report"
              onClick={() => setSelectedCampId(row.id)}
            >
              <BarChart3 className="h-3.5 w-3.5 text-[#111111]" />
            </Button>
          )}

          {row.status === 'Draft' && (
            <Button
              variant="secondary"
              size="sm"
              className="p-1.5"
              title="Launch Campaign"
              onClick={() => startCampaign({ name: row.name, template: row.template, group: row.group, schedule: 'Immediate' })}
            >
              <PlayCircle className="h-3.5 w-3.5 text-[#16A34A]" />
            </Button>
          )}
        </div>
      )
    }
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Broadcast Campaigns</h1>
          <p className="text-[12px] text-[#6B7280]">Dispatch bulk marketing campaigns, template reminders, and track deliveries.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" icon={PhoneCall} onClick={() => setIsTestModalOpen(true)}>
            Send Test Message
          </Button>
          <Button variant="primary" icon={Plus} onClick={() => setIsLaunchModalOpen(true)}>
            Create Campaign
          </Button>
        </div>
      </div>

      {/* Campaigns list table */}
      <DataTable
        columns={columns}
        data={campaigns}
        searchKey="name"
        searchPlaceholder="Search broadcasts..."
        onRowClick={(row) => row.status === 'Completed' && setSelectedCampId(row.id)}
      />

      {/* Create Campaign Modal */}
      <Modal
        isOpen={isLaunchModalOpen}
        onClose={() => setIsLaunchModalOpen(false)}
        title="Launch Broadcast Campaign"
        size="lg"
        footer={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setIsLaunchModalOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleLaunchSubmit} icon={Send}>Start Campaign</Button>
          </div>
        }
      >
        <form onSubmit={handleLaunchSubmit} className="space-y-4">
          <Input
            label="Campaign Campaign Name"
            placeholder="e.g. Clearance Sale Promo"
            value={newCampaign.name}
            onChange={e => setNewCampaign({ ...newCampaign, name: e.target.value })}
            required
          />

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] font-medium text-[#111111] mb-1.5">Approved Template</label>
              <select
                value={newCampaign.template}
                onChange={e => setNewCampaign({ ...newCampaign, template: e.target.value })}
                className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-2 focus:ring-primary text-[#111111]"
                required
              >
                <option value="">Select Template...</option>
                {approvedTemplates.map(t => (
                  <option key={t.id} value={t.name}>#{t.name} ({t.category})</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[12px] font-medium text-[#111111] mb-1.5">Recipient Segment</label>
              <select
                value={newCampaign.group}
                onChange={e => setNewCampaign({ ...newCampaign, group: e.target.value })}
                className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-2 focus:ring-primary text-[#111111]"
                required
              >
                <option value="">Select Group...</option>
                {groups.map(g => (
                  <option key={g.id} value={g.name}>{g.name} ({g.membersCount} contacts)</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-[12px] font-medium text-[#111111] mb-1.5">Sender Number</label>
              <select
                value={newCampaign.whatsappNumber}
                onChange={e => setNewCampaign({ ...newCampaign, whatsappNumber: e.target.value })}
                className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-2 focus:ring-primary text-[#111111]"
              >
                <option value="">Choose Senders...</option>
                {whatsappNumbers.filter(n => n.status === 'Connected').map(n => (
                  <option key={n.id} value={n.phone}>{n.name} ({n.phone})</option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-[12px] font-medium text-[#111111] mb-1.5">Dispatch Schedule</label>
              <select
                value={newCampaign.schedule}
                onChange={e => setNewCampaign({ ...newCampaign, schedule: e.target.value })}
                className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-2 focus:ring-primary text-[#111111]"
              >
                <option value="Immediate">Send Immediately</option>
                <option value="Scheduled">Schedule For Later</option>
              </select>
            </div>
          </div>

          {newCampaign.schedule === 'Scheduled' && (
            <div className="flex gap-2 items-center">
              <Clock className="h-4 w-4 text-[#6B7280]" />
              <Input
                type="datetime-local"
                value={newCampaign.scheduledTime}
                onChange={e => setNewCampaign({ ...newCampaign, scheduledTime: e.target.value })}
                required
              />
            </div>
          )}
        </form>
      </Modal>

      {/* Send Test Message Modal */}
      <Modal
        isOpen={isTestModalOpen}
        onClose={() => setIsTestModalOpen(false)}
        title="Send Test WhatsApp Template"
        footer={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setIsTestModalOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleTestSend}>Send Test</Button>
          </div>
        }
      >
        <form onSubmit={handleTestSend} className="space-y-4">
          <Input
            label="Recipient Mobile (including Country Code)"
            placeholder="e.g. +91 99999 88888"
            value={testNumber}
            onChange={e => setTestNumber(e.target.value)}
            required
          />
          <p className="text-[11px] text-[#6B7280]">Dispatches an instant sandbox test message using the welcome template for validation.</p>
        </form>
      </Modal>

    </div>
  );
};
