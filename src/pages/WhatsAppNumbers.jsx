import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Card, Button, Badge } from '../components/UI';
import { Modal } from '../components/Modal';
import { PhoneOutgoing, Plus, RefreshCw, QrCode, CheckCircle2 } from 'lucide-react';

export const WhatsAppNumbers = () => {
  const { whatsappNumbers, addToast } = useApp();
  const [numbers, setNumbers] = useState(whatsappNumbers);
  const [isConnectModalOpen, setIsConnectModalOpen] = useState(false);
  const [connectStep, setConnectStep] = useState(1); // 1 = Loading, 2 = QR Code, 3 = Connected

  const handleConnectSim = () => {
    setIsConnectModalOpen(true);
    setConnectStep(1);

    // Simulate loading QR
    setTimeout(() => {
      setConnectStep(2);
    }, 1200);
  };

  const completeConnectionSim = () => {
    setConnectStep(3);
    setTimeout(() => {
      const newNum = {
        id: `num_${numbers.length + 1}`,
        phone: "+91 95555 12345",
        name: "Support Desk 2",
        status: "Connected"
      };
      setNumbers([...numbers, newNum]);
      setIsConnectModalOpen(false);
      addToast(`WhatsApp Sender Channel Connected Successfully!`);
    }, 1500);
  };

  const handleDisconnect = (id, name) => {
    setNumbers(numbers.map(n => n.id === id ? { ...n, status: 'Disconnected' } : n));
    addToast(`Disconnected channel "${name}"`);
  };

  const handleReconnect = (id, name) => {
    setNumbers(numbers.map(n => n.id === id ? { ...n, status: 'Connected' } : n));
    addToast(`Re-established bridge for "${name}"`);
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">WhatsApp Senders</h1>
          <p className="text-[12px] text-[#6B7280]">Connect multiple phone lines, monitor network bridges, and scan API QR keys.</p>
        </div>
        <Button variant="primary" icon={Plus} onClick={handleConnectSim}>
          Connect Number
        </Button>
      </div>

      {/* Grid of connected channels */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {numbers.map(num => {
          const isConnected = num.status === 'Connected';
          return (
            <div
              key={num.id}
              className={`bg-white border rounded-custom shadow-soft p-6 flex flex-col justify-between transition-all ${isConnected ? 'border-[#E5E5E5]' : 'border-dashed border-[#DC2626]/40 bg-[#FFEBEE]/10'
                }`}
            >
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`p-2.5 rounded-lg border ${isConnected ? 'bg-[#111111] text-white border-[#111111]' : 'bg-[#FFEBEE] text-[#DC2626] border-[#FFCDD2]'
                      }`}>
                      <PhoneOutgoing className="h-5 w-5" />
                    </div>
                    <div>
                      <h3 className="text-xs font-bold text-[#111111]">{num.name}</h3>
                      <p className="font-mono text-[10px] text-[#6B7280]">{num.phone}</p>
                    </div>
                  </div>
                  <Badge variant={isConnected ? 'success' : 'danger'}>{num.status}</Badge>
                </div>

                <div className="flex justify-between items-center text-[10px] border-t border-[#F5F5F5] pt-4 text-[#6B7280]">
                  <span>Server Bridge: Asia-West</span>
                  <span>Latency: {isConnected ? '35ms' : 'Offline'}</span>
                </div>
              </div>

              <div className="mt-6 pt-4 border-t border-[#F5F5F5] flex justify-end gap-2">
                {isConnected ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="text-xs text-[#DC2626] hover:bg-[#FFEBEE] border-[#E5E5E5]"
                    onClick={() => handleDisconnect(num.id, num.name)}
                  >
                    Disconnect
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="text-xs text-[#16A34A] hover:bg-[#E8F5E9] border-[#E5E5E5]"
                    onClick={() => handleReconnect(num.id, num.name)}
                  >
                    Retry Connection
                  </Button>
                )}
              </div>

            </div>
          );
        })}
      </div>

      {/* QR Connect Simulator Modal */}
      <Modal
        isOpen={isConnectModalOpen}
        onClose={() => setIsConnectModalOpen(false)}
        title="Link WhatsApp Sender Line"
        size="md"
      >
        {connectStep === 1 && (
          <div className="py-12 flex flex-col items-center justify-center text-center space-y-4">
            <RefreshCw className="h-8 w-8 text-[#111111] animate-spin" />
            <h4 className="text-xs font-bold text-[#111111]">Securing WebSocket Connection...</h4>
            <p className="text-[11px] text-[#6B7280]">Initializing webhook bridge with Meta Cloud API servers.</p>
          </div>
        )}

        {connectStep === 2 && (
          <div className="flex flex-col items-center justify-center text-center space-y-6">
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-[#111111]">Scan QR Code with WhatsApp</h4>
              <p className="text-[11px] text-[#6B7280]">Open WhatsApp on your phone, go to Settings &gt; Linked Devices, and scan the key.</p>
            </div>

            {/* Visual QR Code Mockup */}
            <div className="p-4 bg-white border border-[#E5E5E5] rounded-custom shadow-soft relative cursor-pointer" onClick={completeConnectionSim}>
              <QrCode className="h-44 w-44 text-[#111111]" />
              <div className="absolute inset-0 bg-black/5 hover:bg-transparent flex items-center justify-center text-[10px] font-bold text-white uppercase tracking-wider backdrop-blur-[0.5px] transition-all">
                <span className="bg-black/80 px-3 py-1 rounded">Click to Simulate Scan</span>
              </div>
            </div>

            <span className="text-[10px] text-gray-400">QR Code rotates automatically every 20 seconds.</span>
          </div>
        )}

        {connectStep === 3 && (
          <div className="py-12 flex flex-col items-center justify-center text-center space-y-4">
            <CheckCircle2 className="h-10 w-10 text-[#16A34A] animate-bounce" />
            <h4 className="text-xs font-bold text-[#16A34A]">Channel Linked successfully!</h4>
            <p className="text-[11px] text-[#6B7280]">Validating session security and retrieving contacts lists...</p>
          </div>
        )}
      </Modal>

    </div>
  );
};
