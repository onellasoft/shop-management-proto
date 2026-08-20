import React from 'react';
import { useApp } from '../context/AppContext';
import { Badge, Button, Card } from '../components/UI';
import { ArrowLeft, HardDrive, MessageSquare } from 'lucide-react';

export const BusinessDetails = ({ bizId, onClose }) => {
  const { businesses } = useApp();

  const business = businesses.find(b => b.id === bizId);

  if (!business) {
    return (
      <div className="text-center py-12">
        <p className="text-[12px] text-[#6B7280]">Business not found.</p>
        <Button variant="secondary" className="mt-4" onClick={onClose}>Go Back</Button>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Back button header */}
      <div className="flex items-center gap-4">
        <Button variant="secondary" size="sm" onClick={onClose} className="p-2">
          <ArrowLeft className="h-4 w-4 text-[#111111]" />
        </Button>
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-[28px] font-bold text-[#111111] tracking-tight">{business.name}</h1>
            <Badge variant={business.status === 'Active' ? 'success' : 'danger'}>
              {business.status}
            </Badge>
          </div>
          <p className="text-xs text-[#6B7280]">Registered since {business.createdDate} • ID: {business.id}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Left Column: Business & Owner Details */}
        <div className="space-y-8 lg:col-span-2">

          {/* General Information Card */}
          <Card title="Store Profile" subtitle="Ownership details and registered tax information">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 text-sm">
              <div className="space-y-3">
                <div>
                  <span className="block text-[11px] font-semibold text-[#6B7280] uppercase">Owner Full Name</span>
                  <span className="font-medium text-[#111111]">{business.owner}</span>
                </div>
                <div>
                  <span className="block text-[11px] font-semibold text-[#6B7280] uppercase">Primary Email</span>
                  <span className="font-medium text-[#111111]">{business.email}</span>
                </div>
                <div>
                  <span className="block text-[11px] font-semibold text-[#6B7280] uppercase">Mobile Number</span>
                  <span className="font-medium text-[#111111]">{business.mobile}</span>
                </div>
              </div>

              <div className="space-y-3">
                <div>
                  <span className="block text-[11px] font-semibold text-[#6B7280] uppercase">GSTIN Code</span>
                  <span className="font-medium text-[#111111]">{business.gst || "Not Provided"}</span>
                </div>
                <div>
                  <span className="block text-[11px] font-semibold text-[#6B7280] uppercase">PAN Code</span>
                  <span className="font-medium text-[#111111]">{business.pan || "Not Provided"}</span>
                </div>
                <div>
                  <span className="block text-[11px] font-semibold text-[#6B7280] uppercase">Register Address</span>
                  <span className="font-medium text-[#111111]">{business.address || "Not Provided"}</span>
                </div>
              </div>
            </div>
          </Card>

        </div>

        {/* Right Column: Resource Usage */}
        <div className="space-y-8">

          {/* Usage Meters */}
          <Card title="Resource Usage" subtitle="Real-time storage and messaging consumption">
            <div className="space-y-6">

              {/* Storage */}
              <div className="flex justify-between items-center text-xs font-medium">
                <span className="flex items-center gap-1.5 text-[#111111]">
                  <HardDrive className="h-4 w-4 text-[#6B7280]" />
                  Storage Used
                </span>
                <span className="text-[#111111] font-bold">
                  {business.usage.storageUsed} GB
                </span>
              </div>

              {/* Messages */}
              <div className="flex justify-between items-center border-t border-[#F5F5F5] pt-4 text-xs font-medium">
                <span className="flex items-center gap-1.5 text-[#111111]">
                  <MessageSquare className="h-4 w-4 text-[#6B7280]" />
                  Broadcasts Sent
                </span>
                <span className="text-[#111111] font-bold">
                  {business.usage.messagesSent.toLocaleString()} Messages
                </span>
              </div>

              {/* Connected Accounts */}
              <div className="flex justify-between items-center border-t border-[#F5F5F5] pt-4 text-xs font-medium">
                <span className="text-[#111111]">WhatsApp Senders Connected</span>
                <span className="text-[#6B7280] font-bold">{business.usage.whatsappAccountsConnected} Accounts</span>
              </div>

            </div>
          </Card>

        </div>

      </div>
    </div>
  );
};
