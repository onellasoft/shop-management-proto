import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { DataTable } from '../components/DataTable';
import { Badge, Button, Input } from '../components/UI';
import { Drawer } from '../components/Drawer';
import { Modal } from '../components/Modal';
import { Plus, Download, Mail, Phone, MapPin, Tag, RefreshCw } from 'lucide-react';

export const Contacts = () => {
  const { contacts, addContact, deleteContact, messages, activePath, setActivePath } = useApp();

  const [selectedContactId, setSelectedContactId] = useState(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newContact, setNewContact] = useState({ name: '', mobile: '', email: '', city: '', tags: '' });

  // Filters State
  const [cityFilter, setCityFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');

  const selectedContact = contacts.find(c => c.id === selectedContactId);
  const contactHistory = selectedContact
    ? messages.filter(m => m.mobile === selectedContact.mobile || m.contactName === selectedContact.name)
    : [];

  const handleAddSubmit = (e) => {
    e.preventDefault();
    if (!newContact.name || !newContact.mobile) return;

    const formatted = {
      ...newContact,
      tags: newContact.tags ? newContact.tags.split(',').map(t => t.trim()) : ['General']
    };

    addContact(formatted);
    setIsAddModalOpen(false);
    setNewContact({ name: '', mobile: '', email: '', city: '', tags: '' });
  };

  // Extract unique cities for filtering
  const uniqueCities = React.useMemo(() => {
    return ['All', ...new Set(contacts.map(c => c.city).filter(Boolean))];
  }, [contacts]);

  // Filter contacts list
  const filteredData = React.useMemo(() => {
    return contacts.filter(c => {
      const matchCity = cityFilter === 'All' || c.city === cityFilter;
      const matchStatus = statusFilter === 'All' || c.status === statusFilter;
      return matchCity && matchStatus;
    });
  }, [contacts, cityFilter, statusFilter]);

  const handleExport = () => {
    const csvContent = "data:text/csv;charset=utf-8,"
      + ["Name,Mobile,Email,City,Tags,Status", ...contacts.map(c => `"${c.name}","${c.mobile}","${c.email || ''}","${c.city || ''}","${c.tags.join(';')}","${c.status}"`)].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `onella_contacts_export_${new Date().toISOString().split('T')[0]}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const columns = [
    {
      key: 'name',
      title: 'Contact Name',
      sortable: true,
      render: (val, row) => (
        <div>
          <div className="font-semibold text-[#111111]">{val}</div>
          <div className="text-[11px] text-[#6B7280]">ID: {row.id}</div>
        </div>
      )
    },
    {
      key: 'mobile',
      title: 'WhatsApp Mobile',
      sortable: true,
    },
    {
      key: 'email',
      title: 'Email Address',
      sortable: true,
      render: (val) => val || <span className="text-gray-300">-</span>
    },
    {
      key: 'city',
      title: 'City',
      sortable: true,
      render: (val) => val || <span className="text-gray-300">-</span>
    },
    {
      key: 'tags',
      title: 'Segment Tags',
      render: (val) => (
        <div className="flex flex-wrap gap-1">
          {val.map((t, idx) => (
            <span key={idx} className="bg-[#FAFAFA] text-[#6B7280] border border-[#E5E5E5] text-[9px] px-1.5 py-0.2 rounded font-medium">
              {t}
            </span>
          ))}
        </div>
      )
    },
    {
      key: 'status',
      title: 'Status',
      sortable: true,
      render: (val) => (
        <Badge variant={val === 'Active' ? 'success' : 'neutral'}>{val}</Badge>
      )
    }
  ];

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Contacts Database</h1>
          <p className="text-[12px] text-[#6B7280]">Import Excel lists, add new recipients, segment lists, and view campaign histories.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" icon={Download} onClick={handleExport}>
            Export CSV
          </Button>
          <Button variant="secondary" onClick={() => setActivePath('import')}>
            Import Wizard
          </Button>
          <Button variant="primary" icon={Plus} onClick={() => setIsAddModalOpen(true)}>
            Add Contact
          </Button>
        </div>
      </div>

      {/* Main Table */}
      <DataTable
        columns={columns}
        data={filteredData}
        searchKey="name"
        searchPlaceholder="Search contacts by name or phone..."
        onRowClick={(row) => setSelectedContactId(row.id)}
        filterComponent={
          <div className="flex gap-2 text-xs font-semibold">
            {/* City Filter */}
            <select
              value={cityFilter}
              onChange={(e) => setCityFilter(e.target.value)}
              className="bg-white border border-[#E5E5E5] px-3 py-2 rounded-custom focus:outline-none text-[#111111]"
            >
              <option value="All">All Cities</option>
              {uniqueCities.filter(c => c !== 'All').map(city => (
                <option key={city} value={city}>{city}</option>
              ))}
            </select>

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-white border border-[#E5E5E5] px-3 py-2 rounded-custom focus:outline-none text-[#111111]"
            >
              <option value="All">All Statuses</option>
              <option value="Active">Active</option>
              <option value="Inactive">Inactive</option>
            </select>
          </div>
        }
      />

      {/* Contact Details Drawer */}
      <Drawer
        isOpen={!!selectedContactId}
        onClose={() => setSelectedContactId(null)}
        title="Contact Profile"
        size="md"
      >
        {selectedContact && (
          <div className="space-y-6">

            {/* Header Identity card */}
            <div className="flex items-center gap-4 border-b border-[#F5F5F5] pb-5">
              <div className="h-12 w-12 rounded-full bg-[#111111] text-white flex items-center justify-center font-bold text-[18px]">
                {selectedContact.name.split(' ').map(w => w[0]).join('').substring(0, 2).toUpperCase()}
              </div>
              <div>
                <h3 className="text-md font-bold text-[#111111]">{selectedContact.name}</h3>
                <Badge variant={selectedContact.status === 'Active' ? 'success' : 'neutral'}>
                  {selectedContact.status}
                </Badge>
              </div>
            </div>

            {/* Detailed list card */}
            <div className="space-y-4 text-xs font-medium">
              <div className="flex items-center gap-3 text-[#111111]">
                <Phone className="h-4 w-4 text-[#6B7280]" />
                <span>{selectedContact.mobile}</span>
              </div>
              <div className="flex items-center gap-3 text-[#111111]">
                <Mail className="h-4 w-4 text-[#6B7280]" />
                <span>{selectedContact.email || "No Email Provided"}</span>
              </div>
              <div className="flex items-center gap-3 text-[#111111]">
                <MapPin className="h-4 w-4 text-[#6B7280]" />
                <span>City: {selectedContact.city || "Not Provided"}</span>
              </div>
              <div className="flex items-start gap-3 text-[#111111] pt-1">
                <Tag className="h-4 w-4 text-[#6B7280] mt-0.5" />
                <div className="flex flex-wrap gap-1">
                  {selectedContact.tags.map((t, i) => (
                    <span key={i} className="bg-[#FAFAFA] border border-[#E5E5E5] text-[#6B7280] px-2 py-0.5 rounded text-[10px]">
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Recipient Message History */}
            <div className="space-y-4 pt-6 border-t border-[#E5E5E5]">
              <h4 className="text-xs font-bold text-[#111111] uppercase tracking-wide">Message History</h4>
              <div className="space-y-3">
                {contactHistory.length > 0 ? (
                  contactHistory.map(h => (
                    <div key={h.id} className="p-3 bg-[#FAFAFA] border border-[#E5E5E5] rounded-custom text-xs flex justify-between items-center">
                      <div>
                        <p className="font-semibold text-[#111111]">{h.templateName}</p>
                        <p className="text-[10px] text-[#6B7280] mt-0.5">{h.timestamp}</p>
                      </div>
                      <Badge variant={h.status === 'Read' ? 'success' : h.status === 'Delivered' ? 'neutral' : 'danger'}>
                        {h.status}
                      </Badge>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-[#6B7280] italic">No broadcasts sent to this contact yet.</p>
                )}
              </div>
            </div>

            {/* Actions list */}
            <div className="pt-6 border-t border-[#E5E5E5]">
              <Button
                variant="secondary"
                className="w-full text-xs text-[#DC2626] hover:bg-[#FFEBEE] border border-[#E5E5E5]"
                onClick={() => {
                  deleteContact(selectedContact.id);
                  setSelectedContactId(null);
                }}
              >
                Delete Contact
              </Button>
            </div>

          </div>
        )}
      </Drawer>

      {/* Add Contact Modal */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={() => setIsAddModalOpen(false)}
        title="Add Single Contact Recipient"
        footer={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setIsAddModalOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleAddSubmit}>Save Contact</Button>
          </div>
        }
      >
        <form onSubmit={handleAddSubmit} className="space-y-4">
          <Input
            label="Contact Full Name"
            placeholder="e.g. Amit Sharma"
            value={newContact.name}
            onChange={e => setNewContact({ ...newContact, name: e.target.value })}
            required
          />
          <Input
            label="WhatsApp Mobile Number"
            placeholder="e.g. +91 99999 88888"
            value={newContact.mobile}
            onChange={e => setNewContact({ ...newContact, mobile: e.target.value })}
            required
          />
          <Input
            label="Email Address"
            type="email"
            placeholder="e.g. amit@mail.com"
            value={newContact.email}
            onChange={e => setNewContact({ ...newContact, email: e.target.value })}
          />
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="City"
              placeholder="e.g. Mumbai"
              value={newContact.city}
              onChange={e => setNewContact({ ...newContact, city: e.target.value })}
            />
            <Input
              label="Segment Tags (comma separated)"
              placeholder="e.g. VIP, Wholesaler"
              value={newContact.tags}
              onChange={e => setNewContact({ ...newContact, tags: e.target.value })}
            />
          </div>
        </form>
      </Modal>
    </div>
  );
};
