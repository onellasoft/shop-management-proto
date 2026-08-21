import React, { useState, useMemo } from 'react';
import { useApp } from '../context/AppContext';
import { Card, Button, Input, Badge } from '../components/UI';
import { Modal, ConfirmDialog } from '../components/Modal';
import { Plus, Trash2, Edit2, Users, Eye, Search, Tag, X } from 'lucide-react';

export const Groups = () => {
  const { groups, addGroup, updateGroup, deleteGroup, contacts } = useApp();

  // Create/Edit Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editGroupId, setEditGroupId] = useState(null); // null for create, string id for edit
  const [groupName, setGroupName] = useState('');
  const [tagName, setTagName] = useState('');
  const [selectedContactIds, setSelectedContactIds] = useState([]);
  const [contactSearch, setContactSearch] = useState('');

  // View Modal State
  const [isViewModalOpen, setIsViewModalOpen] = useState(false);
  const [viewGroup, setViewGroup] = useState(null);

  // Delete Dialog State
  const [isDeleteOpen, setIsDeleteOpen] = useState(false);
  const [groupToDelete, setGroupToDelete] = useState(null);

  // Filter contacts based on search term inside creation modal
  const filteredContacts = useMemo(() => {
    if (!contactSearch.trim()) return contacts;
    const lower = contactSearch.toLowerCase();
    return contacts.filter(c => 
      c.name.toLowerCase().includes(lower) || 
      c.mobile.toLowerCase().includes(lower) ||
      (c.email && c.email.toLowerCase().includes(lower))
    );
  }, [contacts, contactSearch]);

  // Open creation modal
  const handleCreateOpen = () => {
    setEditGroupId(null);
    setGroupName('');
    setTagName('');
    setSelectedContactIds([]);
    setContactSearch('');
    setIsModalOpen(true);
  };

  // Open edit modal
  const handleEditOpen = (group) => {
    setEditGroupId(group.id);
    setGroupName(group.name || '');
    setTagName(group.tagName || '');
    setSelectedContactIds(group.contactIds || []);
    setContactSearch('');
    setIsModalOpen(true);
  };

  // Open view modal
  const handleViewOpen = (group) => {
    setViewGroup(group);
    setIsViewModalOpen(true);
  };

  // Open delete confirmation
  const handleDeleteOpen = (group) => {
    setGroupToDelete(group);
    setIsDeleteOpen(true);
  };

  // Handle Create/Edit submit
  const handleSubmit = (e) => {
    e.preventDefault();
    if (!groupName.trim()) return;

    if (editGroupId) {
      updateGroup(editGroupId, {
        name: groupName.trim(),
        tagName: tagName.trim(),
        contactIds: selectedContactIds
      });
    } else {
      addGroup(groupName.trim(), tagName.trim(), selectedContactIds);
    }
    setIsModalOpen(false);
  };

  // Handle contact checkbox toggles
  const handleToggleContact = (id) => {
    setSelectedContactIds(prev => 
      prev.includes(id) ? prev.filter(cId => cId !== id) : [...prev, id]
    );
  };

  // Handle Select All visible contacts toggle
  const isAllSelected = useMemo(() => {
    if (filteredContacts.length === 0) return false;
    return filteredContacts.every(c => selectedContactIds.includes(c.id));
  }, [filteredContacts, selectedContactIds]);

  const handleSelectAllToggle = () => {
    if (isAllSelected) {
      // Remove all visible filtered contacts from selection
      const filteredIds = filteredContacts.map(c => c.id);
      setSelectedContactIds(prev => prev.filter(id => !filteredIds.includes(id)));
    } else {
      // Add all missing visible filtered contacts to selection
      const filteredIds = filteredContacts.map(c => c.id);
      setSelectedContactIds(prev => {
        const union = new Set([...prev, ...filteredIds]);
        return Array.from(union);
      });
    }
  };

  // Confirm delete group action
  const handleConfirmDelete = () => {
    if (groupToDelete) {
      deleteGroup(groupToDelete.id);
      setIsDeleteOpen(false);
      setGroupToDelete(null);
    }
  };

  // Map view group's contacts for display
  const viewGroupContactsList = useMemo(() => {
    if (!viewGroup || !viewGroup.contactIds) return [];
    return contacts.filter(c => viewGroup.contactIds.includes(c.id));
  }, [viewGroup, contacts]);

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Contact Groups</h1>
          <p className="text-[12px] text-[#6B7280]">Segment your database into mailing lists for targeted campaigns.</p>
        </div>
        <Button variant="primary" icon={Plus} onClick={handleCreateOpen}>
          Create Group
        </Button>
      </div>

      {/* Groups List */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {groups.map(grp => (
          <div
            key={grp.id}
            className="bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-5 flex flex-col justify-between hover:shadow-md transition-shadow"
          >
            <div className="space-y-4">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-[#FAFAFA] border border-[#E5E5E5] rounded-lg">
                  <Users className="h-5 w-5 text-[#111111]" />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-xs font-bold text-[#111111] truncate">{grp.name}</h3>
                  <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                    <span className="text-[10px] text-[#6B7280]">ID: {grp.id}</span>
                    {grp.tagName && (
                      <span className="bg-[#EEF2F6] text-[#4A5D78] text-[9px] px-1.5 py-0.2 rounded font-semibold border border-[#DCE3EC]">
                        {grp.tagName}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex justify-between items-center text-xs bg-[#FAFAFA] px-3 py-2 border border-[#E5E5E5] rounded-custom">
                <span className="text-[#6B7280]">Members Count</span>
                <span className="font-bold text-[#111111]">{grp.membersCount || 0} Contacts</span>
              </div>
            </div>

            <div className="mt-5 pt-4 border-t border-[#F5F5F5] flex justify-end gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                className="p-1.5 text-[#6B7280] hover:bg-[#F3F4F6] rounded-md"
                onClick={() => handleViewOpen(grp)}
              >
                <Eye className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="p-1.5 text-[#111111] hover:bg-[#F3F4F6] rounded-md"
                onClick={() => handleEditOpen(grp)}
              >
                <Edit2 className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="p-1.5 text-[#DC2626] hover:bg-[#FFEBEE] rounded-md"
                onClick={() => handleDeleteOpen(grp)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Create / Edit Group Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={editGroupId ? "Edit Group Details" : "Create New Contact Group"}
        size="lg"
        footer={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setIsModalOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleSubmit}>{editGroupId ? "Save Changes" : "Create Group"}</Button>
          </div>
        }
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Input
              label="Group Name"
              placeholder="e.g. Inactive Leads June"
              value={groupName}
              onChange={e => setGroupName(e.target.value)}
              required
            />
            <Input
              label="Group Tag (Optional)"
              placeholder="e.g. VIP, Hot Lead"
              value={tagName}
              onChange={e => setTagName(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <label className="text-[11px] font-bold uppercase tracking-wider text-[#6B7280]">
              Assign Contacts ({selectedContactIds.length} Selected)
            </label>
            
            {/* Search and Select All Bar */}
            <div className="flex gap-3 items-center">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-[#9CA3AF]" />
                <input
                  type="text"
                  placeholder="Search contacts by name or number..."
                  value={contactSearch}
                  onChange={e => setContactSearch(e.target.value)}
                  className="w-full bg-white border border-[#E5E5E5] pl-9 pr-4 py-2 rounded-custom text-xs focus:outline-none focus:border-[#111111]"
                />
              </div>
              <label className="flex items-center gap-2 text-xs font-semibold text-[#111111] select-none cursor-pointer border border-[#E5E5E5] px-3 py-2 rounded-custom bg-[#FAFAFA]">
                <input
                  type="checkbox"
                  checked={isAllSelected}
                  onChange={handleSelectAllToggle}
                  className="rounded border-[#D1D5DB] text-[#111111] focus:ring-0 h-3.5 w-3.5"
                />
                Select All
              </label>
            </div>

            {/* Scrollable contact checklist */}
            <div className="max-h-60 overflow-y-auto border border-[#E5E5E5] rounded-custom p-3 space-y-2.5 bg-[#FCFCFC]">
              {filteredContacts.length > 0 ? (
                filteredContacts.map(contact => (
                  <label
                    key={contact.id}
                    className="flex items-start gap-3 p-2 hover:bg-[#F9FAFB] rounded-lg transition-colors cursor-pointer select-none border border-transparent hover:border-[#E5E5E5]"
                  >
                    <input
                      type="checkbox"
                      checked={selectedContactIds.includes(contact.id)}
                      onChange={() => handleToggleContact(contact.id)}
                      className="mt-0.5 rounded border-[#D1D5DB] text-[#111111] focus:ring-0 h-4 w-4"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-[#111111]">{contact.name}</span>
                        {contact.city && <span className="text-[10px] text-[#6B7280]">{contact.city}</span>}
                      </div>
                      <div className="flex items-center justify-between mt-0.5">
                        <span className="text-[10px] text-[#6B7280]">{contact.mobile}</span>
                        {contact.tags && contact.tags.length > 0 && (
                          <div className="flex gap-1">
                            {contact.tags.map((t, idx) => (
                              <span key={idx} className="bg-[#FAFAFA] text-[#6B7280] border border-[#E5E5E5] text-[8px] px-1 py-0.1 rounded font-medium">
                                {t}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </label>
                ))
              ) : (
                <div className="py-8 text-center text-xs text-[#6B7280] italic">
                  No contacts found matching "{contactSearch}"
                </div>
              )}
            </div>
          </div>
        </form>
      </Modal>

      {/* View Group Details Modal */}
      <Modal
        isOpen={isViewModalOpen}
        onClose={() => setIsViewModalOpen(false)}
        title={viewGroup ? `Group: ${viewGroup.name}` : 'Group Details'}
        size="lg"
        footer={
          <Button variant="secondary" onClick={() => setIsViewModalOpen(false)}>Close</Button>
        }
      >
        {viewGroup && (
          <div className="space-y-6">
            <div className="flex justify-between items-start pb-4 border-b border-[#F5F5F5]">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <h4 className="text-sm font-bold text-[#111111]">Metadata & Attributes</h4>
                  {viewGroup.tagName && (
                    <span className="bg-[#EEF2F6] text-[#4A5D78] text-[9px] px-1.5 py-0.2 rounded font-semibold border border-[#DCE3EC]">
                      {viewGroup.tagName}
                    </span>
                  )}
                </div>
                <p className="text-[11px] text-[#6B7280]">Registered ID: {viewGroup.id}</p>
              </div>
              <div className="bg-[#FAFAFA] border border-[#E5E5E5] rounded-custom px-4 py-2 text-right">
                <span className="text-[10px] text-[#6B7280] block">Group Members</span>
                <span className="text-md font-bold text-[#111111]">{viewGroup.membersCount || 0} Contacts</span>
              </div>
            </div>

            <div className="space-y-3">
              <h4 className="text-xs font-bold text-[#111111] uppercase tracking-wide">Members List</h4>
              <div className="max-h-80 overflow-y-auto border border-[#E5E5E5] rounded-custom bg-[#FCFCFC] p-3 space-y-2">
                {viewGroupContactsList.length > 0 ? (
                  viewGroupContactsList.map(contact => (
                    <div key={contact.id} className="p-2.5 bg-white border border-[#E5E5E5] rounded-lg flex items-center justify-between text-xs hover:border-[#CCCCCC] transition-colors">
                      <div>
                        <p className="font-bold text-[#111111]">{contact.name}</p>
                        <p className="text-[10px] text-[#6B7280] mt-0.5">{contact.mobile}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] text-[#111111] font-semibold">{contact.city || '-'}</p>
                        {contact.tags && contact.tags.length > 0 && (
                          <div className="flex gap-1 mt-1 justify-end">
                            {contact.tags.slice(0, 2).map((t, idx) => (
                              <span key={idx} className="bg-[#FAFAFA] text-[#6B7280] border border-[#E5E5E5] text-[8px] px-1.5 py-0.2 rounded font-medium">
                                {t}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-[#6B7280] italic text-center py-6">This group has no contacts assigned.</p>
                )}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        isOpen={isDeleteOpen}
        onClose={() => setIsDeleteOpen(false)}
        onConfirm={handleConfirmDelete}
        title="Delete Contact Group"
        message={groupToDelete ? `Are you sure you want to delete the group "${groupToDelete.name}"? This action cannot be undone.` : ''}
        confirmText="Delete Group"
        cancelText="Cancel"
      />
    </div>
  );
};
