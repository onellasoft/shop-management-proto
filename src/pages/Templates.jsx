import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Badge, Button, Card, Input } from '../components/UI';
import { Modal } from '../components/Modal';
import { FileText, Plus, Eye, MessageSquareCode } from 'lucide-react';

export const Templates = () => {
  const { templates, addTemplate } = useApp();
  const [isEditorOpen, setIsEditorOpen] = useState(false);

  // Editor Form State
  const [newTpl, setNewTpl] = useState({
    name: '', category: 'Marketing', language: 'English (US)', body: 'Hi {{name}}, welcome to {{shop_name}}!'
  });

  // Mock Variable Preview Fillers
  const [variableFillers, setVariableFillers] = useState({
    name: 'Aarav Sharma',
    shop_name: 'Apex Store',
    code: 'ONLLA100',
    order_id: 'ORD-93847',
    amount: '$149.00'
  });

  // Function to replace brackets with local variable mock value
  const getParsedBody = (text) => {
    return text.replace(/\{\{(\w+)\}\}/g, (match, key) => {
      return variableFillers[key] || `[${key}]`;
    });
  };

  // Extract variables list from body e.g. {{name}} -> ['name']
  const getVariablesFromText = (text) => {
    const regex = /\{\{(\w+)\}\}/g;
    const matches = [];
    let match;
    while ((match = regex.exec(text)) !== null) {
      if (!matches.includes(match[1])) {
        matches.push(match[1]);
      }
    }
    return matches;
  };

  const detectedVars = getVariablesFromText(newTpl.body);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!newTpl.name || !newTpl.body) return;

    addTemplate({
      ...newTpl,
      variables: detectedVars
    });

    setIsEditorOpen(false);
    setNewTpl({ name: '', category: 'Marketing', language: 'English (US)', body: 'Hi {{name}}, welcome!' });
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Message Templates</h1>
          <p className="text-[12px] text-[#6B7280]">Draft pre-approved transactional alerts, promotional vouchers, or OTP codes.</p>
        </div>
        <Button variant="primary" icon={Plus} onClick={() => setIsEditorOpen(true)}>
          Create Template
        </Button>
      </div>

      {/* Templates List Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {templates.map(tpl => (
          <div
            key={tpl.id}
            className="bg-white border border-[#E5E5E5] rounded-custom shadow-soft p-5 flex flex-col justify-between"
          >
            <div className="space-y-4">
              <div className="flex justify-between items-start">
                <Badge variant={tpl.category === 'Authentication' ? 'primary' : 'neutral'}>
                  {tpl.category}
                </Badge>
                <Badge variant={tpl.status === 'Approved' ? 'success' : tpl.status === 'Pending' ? 'warning' : 'danger'}>
                  {tpl.status}
                </Badge>
              </div>

              <div>
                <h3 className="text-xs font-bold text-[#111111] font-mono">#{tpl.name}</h3>
                <p className="text-[10px] text-[#6B7280] mt-0.5">Language: {tpl.language} • {tpl.lastModified}</p>
              </div>

              {/* Template Body bubble */}
              <div className="bg-[#FAFAFA] border border-[#E5E5E5] p-3 rounded-lg text-xs font-medium text-[#6B7280] font-sans break-words line-clamp-3">
                {tpl.body}
              </div>
            </div>

            <div className="mt-5 pt-4 border-t border-[#F5F5F5] flex justify-between items-center text-[10px] text-[#6B7280]">
              <span>Vars: {tpl.variables?.length ? tpl.variables.map(v => `{{${v}}}`).join(', ') : 'None'}</span>
              <Button
                variant="secondary"
                size="sm"
                className="p-1 px-2.5 text-[10px]"
                onClick={() => {
                  setNewTpl({ ...tpl });
                  setIsEditorOpen(true);
                }}
              >
                Inspect
              </Button>
            </div>
          </div>
        ))}
      </div>

      {/* Editor Modal containing Live Preview Panels */}
      <Modal
        isOpen={isEditorOpen}
        onClose={() => setIsEditorOpen(false)}
        title="WhatsApp Template Builder"
        size="2xl"
        footer={
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setIsEditorOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={handleSubmit}>Submit for Meta Approval</Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">

          {/* Left Panel: Form Settings */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <Input
              label="Template Name"
              placeholder="e.g. summer_clearance_sale"
              value={newTpl.name}
              onChange={e => setNewTpl({ ...newTpl, name: e.target.value.toLowerCase().replace(/\s+/g, '_') })}
              required
            />

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-[12px] font-medium text-[#111111] mb-1.5">Category</label>
                <select
                  value={newTpl.category}
                  onChange={e => setNewTpl({ ...newTpl, category: e.target.value })}
                  className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-2 focus:ring-primary text-[#111111]"
                >
                  <option value="Marketing">Marketing (Promos)</option>
                  <option value="Utility">Utility (Alerts/Orders)</option>
                  <option value="Authentication">Authentication (OTPs)</option>
                </select>
              </div>
              <Input
                label="Language"
                value={newTpl.language}
                onChange={e => setNewTpl({ ...newTpl, language: e.target.value })}
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-[12px] font-medium text-[#111111]">Message Body Text</label>
              <textarea
                value={newTpl.body}
                onChange={e => setNewTpl({ ...newTpl, body: e.target.value })}
                rows={5}
                className="w-full text-xs p-3.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-2 focus:ring-primary text-[#111111]"
                placeholder="Insert text. Use double brackets for variables e.g. {{name}}, {{code}}."
                required
              />
            </div>

            {/* Dynamic variable inputs based on detected variables */}
            {detectedVars.length > 0 && (
              <div className="space-y-3 pt-3 border-t border-[#F5F5F5]">
                <h5 className="text-[11px] font-bold text-[#111111] uppercase tracking-wide">Test Variable Inputs:</h5>
                <div className="grid grid-cols-2 gap-3">
                  {detectedVars.map(v => (
                    <Input
                      key={v}
                      label={`{{${v}}}`}
                      value={variableFillers[v] || ''}
                      onChange={e => setVariableFillers({ ...variableFillers, [v]: e.target.value })}
                    />
                  ))}
                </div>
              </div>
            )}
          </form>

          {/* Right Panel: Simulated WhatsApp Phone Preview */}
          <div className="flex flex-col items-center justify-center bg-[#FAFAFA] border border-[#E5E5E5] rounded-custom p-6 relative">
            <h5 className="text-[10px] font-semibold text-[#6B7280] uppercase tracking-wider absolute top-4">WhatsApp Live Preview</h5>

            {/* Phone container */}
            <div className="w-full max-w-[260px] bg-[#E5E5E5]/20 border-[6px] border-[#111111] rounded-[24px] overflow-hidden flex flex-col shadow-soft mt-6">
              {/* Top notch */}
              <div className="bg-[#111111] h-4.5 w-full flex items-center justify-center">
                <span className="text-[8px] text-white">WhatsApp Sandbox</span>
              </div>

              {/* Phone Body message container */}
              <div className="flex-1 bg-[#ECE5DD] p-3.5 min-h-[220px] flex flex-col justify-end">
                <div className="bg-white p-3 rounded-lg shadow-sm text-[11px] text-[#111111] max-w-[90%] space-y-1.5 self-start break-words border-l-[3px] border-l-[#16A34A]">
                  <p className="whitespace-pre-line">{getParsedBody(newTpl.body)}</p>
                  <span className="block text-[8px] text-[#6B7280] text-right">09:41 AM</span>
                </div>
              </div>
            </div>
          </div>

        </div>
      </Modal>
    </div>
  );
};
