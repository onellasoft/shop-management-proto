import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Card, Button, Input } from '../components/UI';
import { Save } from 'lucide-react';

export const BusinessAdminSettings = () => {
  const { addToast } = useApp();
  const [activeTab, setActiveTab] = useState('Company');

  // States
  const [company, setCompany] = useState({ name: 'Organic Grocers Ltd.', timezone: 'Asia/Kolkata', language: 'English (US)' });
  const [notif, setNotif] = useState({ emailAlerts: true, msgFails: true, limitWarnings: true });

  const handleSave = (e) => {
    e.preventDefault();
    addToast('Company configurations saved successfully!');
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Company Settings</h1>
        <p className="text-[12px] text-[#6B7280]">Adjust storefront profiles, mailing timezones, billing notification preferences, and languages.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">

        {/* Left tabs */}
        <div className="flex flex-col gap-1 text-left">
          {['Company Profile', 'Alert Preferences'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-xs font-semibold rounded-custom transition-all text-left ${activeTab === tab
                ? 'bg-white border border-[#E5E5E5] text-[#111111] shadow-soft font-bold'
                : 'text-[#6B7280] hover:text-[#111111] hover:bg-[#FAFAFA]'
                }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Right side form */}
        <div className="lg:col-span-3">
          <form onSubmit={handleSave}>

            {activeTab === 'Company Profile' && (
              <Card title="Company Profile Details" subtitle="Public identifiers for invoicing and template signatures">
                <div className="space-y-4">
                  <Input
                    label="Registered Legal Entity Name"
                    value={company.name}
                    onChange={e => setCompany({ ...company, name: e.target.value })}
                  />
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-[12px] font-medium text-[#111111] mb-1.5">Broadcast Timezone</label>
                      <select
                        value={company.timezone}
                        onChange={e => setCompany({ ...company, timezone: e.target.value })}
                        className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none text-[#111111]"
                      >
                        <option value="Asia/Kolkata">Asia/Kolkata (IST)</option>
                        <option value="America/New_York">America/New_York (EST)</option>
                        <option value="Europe/London">Europe/London (GMT)</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-[12px] font-medium text-[#111111] mb-1.5">Primary Language</label>
                      <select
                        value={company.language}
                        onChange={e => setCompany({ ...company, language: e.target.value })}
                        className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none text-[#111111]"
                      >
                        <option value="English (US)">English (US)</option>
                        <option value="Hindi (IN)">Hindi (IN)</option>
                        <option value="Spanish (ES)">Spanish (ES)</option>
                      </select>
                    </div>
                  </div>

                  <div className="pt-4 flex justify-end">
                    <Button variant="primary" type="submit" icon={Save}>Save Company Details</Button>
                  </div>
                </div>
              </Card>
            )}

            {activeTab === 'Alert Preferences' && (
              <Card title="Workspace Alerts" subtitle="Set parameters for delivery notifications">
                <div className="space-y-4">

                  <div className="space-y-3.5">

                    {/* Email alerts */}
                    <label className="flex items-center gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={notif.emailAlerts}
                        onChange={e => setNotif({ ...notif, emailAlerts: e.target.checked })}
                        className="rounded border-[#E5E5E5] text-[#111111] focus:ring-[#111111] h-4 w-4"
                      />
                      <div>
                        <span className="block text-xs font-bold text-[#111111]">Daily Email Digests</span>
                        <span className="block text-[10px] text-[#6B7280]">Email summaries of campaign engagement metrics.</span>
                      </div>
                    </label>

                    {/* Fails alerts */}
                    <label className="flex items-center gap-3 border-t border-[#F5F5F5] pt-4.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={notif.msgFails}
                        onChange={e => setNotif({ ...notif, msgFails: e.target.checked })}
                        className="rounded border-[#E5E5E5] text-[#111111] focus:ring-[#111111] h-4 w-4"
                      />
                      <div>
                        <span className="block text-xs font-bold text-[#111111]">Deliverability Fail Warnings</span>
                        <span className="block text-[10px] text-[#6B7280]">Notify in-app immediately if a template failure rate exceeds 5%.</span>
                      </div>
                    </label>

                    {/* Limit alerts */}
                    <label className="flex items-center gap-3 border-t border-[#F5F5F5] pt-4.5 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={notif.limitWarnings}
                        onChange={e => setNotif({ ...notif, limitWarnings: e.target.checked })}
                        className="rounded border-[#E5E5E5] text-[#111111] focus:ring-[#111111] h-4 w-4"
                      />
                      <div>
                        <span className="block text-xs font-bold text-[#111111]">Subscription Limit Warnings</span>
                        <span className="block text-[10px] text-[#6B7280]">Alert when storage or broadcast logs hit 90% quota.</span>
                      </div>
                    </label>

                  </div>

                  <div className="pt-6 border-t border-[#F5F5F5] flex justify-end">
                    <Button variant="primary" type="submit" icon={Save}>Save Alert Prefs</Button>
                  </div>

                </div>
              </Card>
            )}

          </form>
        </div>

      </div>
    </div>
  );
};
