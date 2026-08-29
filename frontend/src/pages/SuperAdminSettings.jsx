import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Card, Button, Input, Badge } from '../components/UI';
import { Key, Save, RefreshCw, Copy } from 'lucide-react';

export const SuperAdminSettings = () => {
  const { addToast } = useApp();
  const [activeTab, setActiveTab] = useState('Brand');

  // Mock Settings Values
  const [brand, setBrand] = useState({ name: 'Onella Platform', domain: 'onella.com', color: '#111111' });
  const [smtp, setSmtp] = useState({ host: 'smtp.sendgrid.net', port: '587', user: 'apikey' });
  const [sms, setSms] = useState({ provider: 'Twilio', sid: 'AC1029384756afec', token: '••••••••••••••••••••' });
  const [apiKey, setApiKey] = useState('onella_live_51NzhS1B1wK2L3k4P5q6R7s8T9u0V');

  const handleRegenKey = () => {
    const newKey = 'onella_live_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
    setApiKey(newKey);
    addToast('New API Key regenerated successfully!');
  };

  const handleCopyKey = () => {
    navigator.clipboard.writeText(apiKey);
    addToast('API Key copied to clipboard!');
  };

  const handleSave = (e) => {
    e.preventDefault();
    addToast('Configuration settings updated successfully!');
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">System Settings</h1>
        <p className="text-[12px] text-[#6B7280]">Configure SMTP connections, SMS gateways, White-label branding, and manage global API credentials.</p>
      </div>

      {/* Tabs Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">

        {/* Left Side Tab Navigation */}
        <div className="flex flex-col gap-1 text-left">
          {['Brand', 'Email & SMS', 'Payments Gateway', 'API Keys'].map(tab => (
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

        {/* Right Side Settings Panels */}
        <div className="lg:col-span-3">
          <form onSubmit={handleSave}>

            {activeTab === 'Brand' && (
              <Card title="White-label Branding" subtitle="Configure logo branding and subdomains for clients">
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <Input
                      label="Portal Platform Name"
                      value={brand.name}
                      onChange={e => setBrand({ ...brand, name: e.target.value })}
                    />
                    <Input
                      label="Global App Domain"
                      value={brand.domain}
                      onChange={e => setBrand({ ...brand, domain: e.target.value })}
                    />
                  </div>
                  <Input
                    label="Primary Palette Accent (HEX)"
                    value={brand.color}
                    onChange={e => setBrand({ ...brand, color: e.target.value })}
                  />
                  <div className="pt-4 flex justify-end">
                    <Button variant="primary" type="submit" icon={Save}>Save Branding</Button>
                  </div>
                </div>
              </Card>
            )}

            {activeTab === 'Email & SMS' && (
              <div className="space-y-6">
                <Card title="SMTP Configuration" subtitle="Outgoing transactional mailing gateway details">
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <Input
                        label="SMTP Host"
                        value={smtp.host}
                        onChange={e => setSmtp({ ...smtp, host: e.target.value })}
                      />
                      <Input
                        label="Port"
                        value={smtp.port}
                        onChange={e => setSmtp({ ...smtp, port: e.target.value })}
                      />
                    </div>
                    <Input
                      label="Authentication User ID"
                      value={smtp.user}
                      onChange={e => setSmtp({ ...smtp, user: e.target.value })}
                    />
                  </div>
                </Card>

                <Card title="WhatsApp / SMS Providers" subtitle="Outgoing messaging API details">
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <Input
                        label="Gateway Provider"
                        value={sms.provider}
                        onChange={e => setSms({ ...sms, provider: e.target.value })}
                      />
                      <Input
                        label="Account SID"
                        value={sms.sid}
                        onChange={e => setSms({ ...sms, sid: e.target.value })}
                      />
                    </div>
                    <Input
                      label="Authentication Secret Token"
                      type="password"
                      value={sms.token}
                      onChange={e => setSms({ ...sms, token: e.target.value })}
                    />
                    <div className="pt-4 flex justify-end">
                      <Button variant="primary" type="submit" icon={Save}>Save Gateways</Button>
                    </div>
                  </div>
                </Card>
              </div>
            )}

            {activeTab === 'Payments Gateway' && (
              <Card title="Stripe / Razorpay Credentials" subtitle="Mock credentials for client subscription collection">
                <div className="space-y-4">
                  <Input label="Webhook Endpoint url" placeholder="https://onella.com/api/v1/billing/webhook" />
                  <div className="grid grid-cols-2 gap-4">
                    <Input label="Stripe Public Key" placeholder="pk_live_••••••••" />
                    <Input label="Stripe Secret Key" type="password" placeholder="sk_live_••••••••" />
                  </div>
                  <div className="pt-4 flex justify-end">
                    <Button variant="primary" type="submit" icon={Save}>Save Gateway Keys</Button>
                  </div>
                </div>
              </Card>
            )}

            {activeTab === 'API Keys' && (
              <Card title="Global Platform Developer Credentials" subtitle="Generate live keys to access Onella merchant API feeds">
                <div className="space-y-4">
                  <div className="space-y-2">
                    <label className="block text-[12px] font-semibold text-[#111111]">Platform API Secret</label>
                    <div className="flex gap-2">
                      <div className="flex-1 bg-[#FAFAFA] border border-[#E5E5E5] px-4 py-2.5 rounded-custom font-mono text-xs flex items-center justify-between text-[#111111]">
                        <span>{apiKey}</span>
                        <Badge variant="success">Live</Badge>
                      </div>
                      <Button variant="secondary" onClick={handleCopyKey} type="button" icon={Copy}>Copy</Button>
                    </div>
                  </div>

                  <div className="pt-4 border-t border-[#F5F5F5] flex items-center justify-between text-xs text-[#6B7280]">
                    <span>Last regenerated: 2 days ago</span>
                    <Button variant="primary" onClick={handleRegenKey} type="button" icon={RefreshCw}>Regenerate Secret Key</Button>
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
