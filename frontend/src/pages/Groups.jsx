import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Card, Button, Input } from '../components/UI';
import { Plus, Trash2, Edit2, Users } from 'lucide-react';

export const Groups = () => {
  const { groups, addGroup, deleteGroup } = useApp();
  const [newGroupName, setNewGroupName] = useState('');

  const handleAdd = (e) => {
    e.preventDefault();
    if (!newGroupName.trim()) return;
    addGroup(newGroupName.trim());
    setNewGroupName('');
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Contact Groups</h1>
          <p className="text-[12px] text-[#6B7280]">Segment your database into mailing lists for targeted campaigns.</p>
        </div>
      </div>

      {/* Create Group Card */}
      <Card title="Create Contact Group" subtitle="Quickly create segments for templates distribution">
        <form onSubmit={handleAdd} className="flex gap-4 items-end max-w-lg">
          <Input
            label="Group Name"
            placeholder="e.g. Inactive Leads June"
            value={newGroupName}
            onChange={e => setNewGroupName(e.target.value)}
          />
          <Button variant="primary" icon={Plus} type="submit">Create</Button>
        </form>
      </Card>

      {/* Groups List */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
        {groups.map(grp => (
          <div
            key={grp.id}
            className="bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-5 flex flex-col justify-between"
          >
            <div className="space-y-4">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-[#FAFAFA] border border-[#E5E5E5] rounded-lg">
                  <Users className="h-5 w-5 text-[#111111]" />
                </div>
                <div>
                  <h3 className="text-xs font-bold text-[#111111]">{grp.name}</h3>
                  <span className="text-[10px] text-[#6B7280]">ID: {grp.id}</span>
                </div>
              </div>

              <div className="flex justify-between items-center text-xs bg-[#FAFAFA] px-3 py-2 border border-[#E5E5E5] rounded-custom">
                <span className="text-[#6B7280]">Members Count</span>
                <span className="font-bold text-[#111111]">{grp.membersCount} Contacts</span>
              </div>
            </div>

            <div className="mt-5 pt-4 border-t border-[#F5F5F5] flex justify-end gap-1.5">
              <Button
                variant="ghost"
                size="sm"
                className="p-1.5 text-[#DC2626] hover:bg-[#FFEBEE]"
                onClick={() => deleteGroup(grp.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}
      </div>

    </div>
  );
};
