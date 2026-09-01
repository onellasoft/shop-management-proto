import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Globe, Users, Settings, PlusCircle, CheckSquare, Shield, HelpCircle, PhoneCall, ChevronRight } from 'lucide-react';
import { useApp, ROLES, isSuperAdmin } from '../context/AppContext';

export const CommandPalette = () => {
  const {
    isCommandPaletteOpen,
    setIsCommandPaletteOpen,
    currentRole,
    setCurrentRole,
    setActivePath,
    businesses,
    contacts
  } = useApp();

  const [query, setQuery] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef(null);

  // Toggle Command Palette with Ctrl+K / Cmd+K
  useEffect(() => {
    const handleKeyDown = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [setIsCommandPaletteOpen]);

  // Focus Input on Open
  useEffect(() => {
    if (isCommandPaletteOpen) {
      setQuery('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isCommandPaletteOpen]);

  // Menu Options depending on role
  const getStaticOptions = () => {
    const common = [
      {
        id: 'switch_role',
        title: `Switch to ${isSuperAdmin(currentRole) ? 'Business Admin' : 'Agency Admin'}`,
        category: 'Actions',
        icon: Globe,
        action: () => {
          setCurrentRole(isSuperAdmin(currentRole) ? ROLES.AGENCYADMIN : ROLES.SUPERADMIN);
          setActivePath('dashboard');
        },
      },
    ];

    if (isSuperAdmin(currentRole)) {
      return [
        ...common,
        { id: 'nav_dash', title: 'Go to Super Admin Dashboard', category: 'Navigation', icon: Globe, action: () => setActivePath('dashboard') },
        { id: 'nav_biz', title: 'Go to Business Management', category: 'Navigation', icon: Users, action: () => setActivePath('businesses') },
        { id: 'nav_kyc', title: 'Go to KYC Verification', category: 'Navigation', icon: Shield, action: () => setActivePath('kyc') },
        { id: 'nav_modules', title: 'Go to Module Management', category: 'Navigation', icon: Settings, action: () => setActivePath('modules') },
        { id: 'nav_subs', title: 'Go to Subscription Plans', category: 'Navigation', icon: CheckSquare, action: () => setActivePath('subscriptions') },
        { id: 'nav_users', title: 'Go to Platform Users', category: 'Navigation', icon: Users, action: () => setActivePath('users') },
        { id: 'nav_logs', title: 'Go to Audit Logs', category: 'Navigation', icon: HelpCircle, action: () => setActivePath('audit_logs') },
        { id: 'nav_settings', title: 'Go to System Settings', category: 'Navigation', icon: Settings, action: () => setActivePath('settings') },
      ];
    } else {
      return [
        ...common,
        { id: 'nav_dash_biz', title: 'Go to Business Dashboard', category: 'Navigation', icon: Globe, action: () => setActivePath('dashboard') },
        { id: 'nav_contacts', title: 'Go to Contacts', category: 'Navigation', icon: Users, action: () => setActivePath('contacts') },
        { id: 'nav_import', title: 'Start Import Wizard', category: 'Navigation', icon: PlusCircle, action: () => setActivePath('import') },
        { id: 'nav_groups', title: 'Go to Groups', category: 'Navigation', icon: Users, action: () => setActivePath('groups') },
        { id: 'nav_templates', title: 'Go to Templates', category: 'Navigation', icon: CheckSquare, action: () => setActivePath('templates') },
        { id: 'nav_campaigns', title: 'Go to Campaigns', category: 'Navigation', icon: PlusCircle, action: () => setActivePath('campaigns') },
        { id: 'nav_numbers', title: 'Go to WhatsApp Numbers', category: 'Navigation', icon: PhoneCall, action: () => setActivePath('whatsapp_numbers') },
        { id: 'nav_settings_biz', title: 'Go to Company Settings', category: 'Navigation', icon: Settings, action: () => setActivePath('settings') },
      ];
    }
  };

  // Filter Items
  const filteredItems = React.useMemo(() => {
    const staticOpts = getStaticOptions();
    let dynamicOpts = [];

    if (query.trim()) {
      if (isSuperAdmin(currentRole)) {
        dynamicOpts = businesses
          .filter(b => b.name.toLowerCase().includes(query.toLowerCase()) || b.owner.toLowerCase().includes(query.toLowerCase()))
          .slice(0, 5)
          .map(b => ({
            id: `biz_${b.id}`,
            title: `Business: ${b.name} (${b.owner})`,
            category: 'Businesses',
            icon: Users,
            action: () => {
              setActivePath('businesses');
              // Optionally trigger detail view if implemented
            }
          }));
      } else {
        dynamicOpts = contacts
          .filter(c => c.name.toLowerCase().includes(query.toLowerCase()) || c.mobile.includes(query))
          .slice(0, 5)
          .map(c => ({
            id: `c_${c.id}`,
            title: `Contact: ${c.name} (${c.mobile})`,
            category: 'Contacts',
            icon: Users,
            action: () => {
              setActivePath('contacts');
            }
          }));
      }
    }

    const items = [...staticOpts, ...dynamicOpts];

    if (!query) return items;
    return items.filter(item => item.title.toLowerCase().includes(query.toLowerCase()) || item.category.toLowerCase().includes(query.toLowerCase()));
  }, [query, currentRole, businesses, contacts]);

  // Handle Keyboard Navigation
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!isCommandPaletteOpen) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex(prev => (prev + 1) % filteredItems.length);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex(prev => (prev - 1 + filteredItems.length) % filteredItems.length);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredItems[selectedIndex]) {
          filteredItems[selectedIndex].action();
          setIsCommandPaletteOpen(false);
        }
      } else if (e.key === 'Escape') {
        setIsCommandPaletteOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isCommandPaletteOpen, filteredItems, selectedIndex, setIsCommandPaletteOpen]);

  // Group items by category
  const categories = filteredItems.reduce((acc, item) => {
    if (!acc[item.category]) acc[item.category] = [];
    acc[item.category].push(item);
    return acc;
  }, {});

  // Generate linear index lookup for grouped display
  let flatIndex = 0;
  const categorizedItems = Object.entries(categories).map(([catName, catItems]) => {
    const itemsWithIndex = catItems.map(item => {
      const currentFlatIndex = flatIndex;
      flatIndex++;
      return { ...item, flatIndex: currentFlatIndex };
    });
    return [catName, itemsWithIndex];
  });

  return (
    <AnimatePresence>
      {isCommandPaletteOpen && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] px-4">
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 0.4 }}
            exit={{ opacity: 0 }}
            onClick={() => setIsCommandPaletteOpen(false)}
            className="absolute inset-0 bg-black"
          />

          {/* Palette Box */}
          <motion.div
            initial={{ opacity: 0, y: -20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.98 }}
            transition={{ duration: 0.2 }}
            className="relative w-full max-w-lg bg-white border border-[#E5E5E5] rounded-custom shadow-premium overflow-hidden z-10 flex flex-col"
          >
            {/* Input field */}
            <div className="flex items-center px-4 border-b border-[#E5E5E5]">
              <Search className="h-4 w-4 text-[#6B7280] mr-3" />
              <input
                ref={inputRef}
                type="text"
                placeholder="Type a command or search..."
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setSelectedIndex(0);
                }}
                className="w-full py-4 text-sm text-[#111111] placeholder-[#6B7280] bg-transparent focus:outline-none"
              />
              <kbd className="hidden sm:inline-flex items-center px-2 py-0.5 rounded border border-[#E5E5E5] text-[10px] text-[#6B7280] font-sans">
                ESC
              </kbd>
            </div>

            {/* List items */}
            <div className="max-h-[320px] overflow-y-auto p-2 no-scrollbar">
              {filteredItems.length > 0 ? (
                categorizedItems.map(([catName, catItems]) => (
                  <div key={catName} className="mb-2">
                    <h4 className="text-[10px] font-semibold text-[#6B7280] uppercase tracking-wider px-3 py-2">
                      {catName}
                    </h4>
                    <div className="space-y-0.5">
                      {catItems.map((item) => {
                        const Icon = item.icon;
                        const isSelected = item.flatIndex === selectedIndex;
                        return (
                          <div
                            key={item.id}
                            onClick={() => {
                              item.action();
                              setIsCommandPaletteOpen(false);
                            }}
                            className={`flex items-center justify-between px-3 py-2.5 rounded-lg cursor-pointer transition-colors duration-150 ${isSelected ? 'bg-[#FAFAFA] text-[#111111]' : 'text-[#6B7280] hover:bg-[#F5F5F5]/50'
                              }`}
                          >
                            <div className="flex items-center gap-3">
                              <Icon className={`h-4 w-4 ${isSelected ? 'text-[#111111]' : 'text-[#6B7280]'}`} />
                              <span className="text-sm font-medium">{item.title}</span>
                            </div>
                            {isSelected && (
                              <ChevronRight className="h-4 w-4 text-[#111111] animate-pulse" />
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-6 text-center text-[12px] text-[#6B7280]">
                  No results found for "{query}"
                </div>
              )}
            </div>

            {/* Footer help */}
            <div className="flex items-center justify-between px-4 py-2.5 bg-[#FAFAFA] border-t border-[#E5E5E5] text-[10px] text-[#6B7280]">
              <div className="flex items-center gap-1.5">
                <span>Navigate:</span>
                <kbd className="px-1 bg-white border border-[#E5E5E5] rounded">↑↓</kbd>
                <span>Select:</span>
                <kbd className="px-1 bg-white border border-[#E5E5E5] rounded">Enter</kbd>
              </div>
              <div>Press <kbd className="px-1 bg-white border border-[#E5E5E5] rounded">Ctrl + K</kbd> to toggle</div>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
};
