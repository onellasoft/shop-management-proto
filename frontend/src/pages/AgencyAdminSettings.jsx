import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Card, Button, Input } from '../components/UI';
import { Save } from 'lucide-react';

/**
 * AgencyAdminSettings — agency-scoped settings. Lets an agency admin manage
 * their agency profile and notification preferences. This is distinct from the
 * platform-wide SuperAdminSettings (which controls global gateways/branding).
 */
export const AgencyAdminSettings = () => {
  const { agencies, userInfo, updateAgency, addToast } = useApp();
  const [activeTab, setActiveTab] = useState('Profile');

  const agencyId = userInfo?.agency_id ?? agencies[0]?.id ?? null;
  const agency = agencies.find(a => a.id === agencyId);

  const [profile, setProfile] = useState({
    name: agency?.name ?? '',
    owner: agency?.owner ?? '',
    email: agency?.email ?? '',
    mobile: agency?.mobile ?? '',
  });

  const [prefs, setPrefs] = useState({
    campaignAlerts: true,
    weeklyReport: true,
    businessSuspension: true,
  });

  const handleSaveProfile = (e) => {
    e.preventDefault();
    if (agencyId) updateAgency(agencyId, profile);
    else addToast('Agency profile updated!');
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Agency Settings</h1>
        <p className="text-[12px] text-[#6B7280]">Manage your agency profile and notification preferences.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
        {/* Tab nav */}
        <div className="flex flex-col gap-1 text-left">
          {['Profile', 'Notifications'].map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-3 text-xs font-semibold rounded-custom transition-all text-left ${
                activeTab === tab
                  ? 'bg-white border border-[#E5E5E5] text-[#111111] shadow-soft font-bold'
                  : 'text-[#6B7280] hover:text-[#111111] hover:bg-[#FAFAFA]'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Panels */}
        <div className="lg:col-span-3">
          {activeTab === 'Profile' && (
            <Card title="Agency Profile" subtitle="Your agency's public and contact details">
              <form onSubmit={handleSaveProfile} className="space-y-4">
                <Input
                  label="Agency Name"
                  value={profile.name}
                  onChange={e => setProfile({ ...profile, name: e.target.value })}
                />
                <Input
                  label="Owner Name"
                  value={profile.owner}
                  onChange={e => setProfile({ ...profile, owner: e.target.value })}
                />
                <div className="grid grid-cols-2 gap-4">
                  <Input
                    label="Email"
                    type="email"
                    value={profile.email}
                    onChange={e => setProfile({ ...profile, email: e.target.value })}
                  />
                  <Input
                    label="Mobile"
                    value={profile.mobile}
                    onChange={e => setProfile({ ...profile, mobile: e.target.value })}
                  />
                </div>
                <div className="pt-4 flex justify-end">
                  <Button variant="primary" type="submit" icon={Save}>Save Profile</Button>
                </div>
              </form>
            </Card>
          )}

          {activeTab === 'Notifications' && (
            <Card title="Notification Preferences" subtitle="Choose which agency alerts you receive">
              <div className="space-y-4">
                {[
                  { key: 'campaignAlerts', label: 'Campaign completion alerts', desc: 'Get notified when a business completes a campaign.' },
                  { key: 'weeklyReport', label: 'Weekly summary report', desc: 'A weekly digest of activity across your businesses.' },
                  { key: 'businessSuspension', label: 'Business suspension alerts', desc: 'Get notified when a business is suspended or reactivated.' },
                ].map(item => (
                  <div key={item.key} className="flex items-center justify-between border-b border-[#F5F5F5] pb-4 last:border-0 last:pb-0">
                    <div>
                      <p className="text-xs font-semibold text-[#111111]">{item.label}</p>
                      <p className="text-[11px] text-[#6B7280] mt-0.5">{item.desc}</p>
                    </div>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        className="sr-only peer"
                        checked={prefs[item.key]}
                        onChange={() => setPrefs({ ...prefs, [item.key]: !prefs[item.key] })}
                      />
                      <div className="custom-toggle w-9 h-5 bg-[#E5E5E5] rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-[#111111] transition-all"></div>
                    </label>
                  </div>
                ))}
                <div className="pt-4 flex justify-end">
                  <Button variant="primary" type="button" icon={Save} onClick={() => addToast('Preferences saved!')}>
                    Save Preferences
                  </Button>
                </div>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
};
