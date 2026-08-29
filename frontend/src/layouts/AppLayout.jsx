import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useApp } from '../context/AppContext';
import {
  Menu, X, Bell, Search, ChevronDown, LogOut, ShieldAlert, User,
  LayoutDashboard, Building2, UserCheck, Settings, FileText,
  Layers, CreditCard, Users, History, FileSpreadsheet, Group,
  Send, PhoneOutgoing, Sliders
} from 'lucide-react';
import { Avatar, Badge, Button } from '../components/UI';

export const AppLayout = ({ children }) => {
  const {
    currentRole,
    setCurrentRole,
    setIsCommandPaletteOpen,
    notifications,
    setNotifications,
    addToast,
    logout
  } = useApp();

  const location = useLocation();
  const navigate = useNavigate();
  const pathname = location.pathname;

  const getActivePathFromPathname = (path) => {
    if (path.startsWith('/super-admin/dashboard')) return 'dashboard';
    if (path.startsWith('/business/dashboard')) return 'dashboard';
    if (path.startsWith('/business-listing') || path.startsWith('/business-register') || path.startsWith('/business-details')) return 'businesses';
    if (path.startsWith('/super-admin/settings')) return 'settings';
    
    if (path.startsWith('/contacts')) return 'contacts';
    if (path.startsWith('/import')) return 'import';
    if (path.startsWith('/groups')) return 'groups';
    if (path.startsWith('/templates')) return 'templates';
    if (path.startsWith('/campaigns')) return 'campaigns';
    if (path.startsWith('/whatsapp-numbers')) return 'whatsapp_numbers';
    if (path.startsWith('/business/settings')) return 'settings';

    return 'dashboard';
  };

  const activePath = getActivePathFromPathname(pathname);

  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isNotificationOpen, setIsNotificationOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);

  // Generate dynamic sidebar items based on role
  const getSidebarItems = () => {
    if (currentRole === 'super_admin') {
      return [
        { path: 'dashboard', url: '/super-admin/dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { path: 'businesses', url: '/business-listing', label: 'Businesses', icon: Building2 },
        { path: 'settings', url: '/super-admin/settings', label: 'Settings', icon: Settings },
      ];
    } else {
      return [
        { path: 'dashboard', url: '/business/dashboard', label: 'Dashboard', icon: LayoutDashboard },
        { path: 'contacts', url: '/contacts', label: 'Contacts', icon: Users },
        { path: 'import', url: '/import', label: 'Import Wizard', icon: FileSpreadsheet },
        { path: 'groups', url: '/groups', label: 'Groups', icon: Group },
        { path: 'templates', url: '/templates', label: 'Templates', icon: FileText },
        { path: 'campaigns', url: '/campaigns', label: 'Campaigns', icon: Send },
        { path: 'whatsapp_numbers', url: '/whatsapp-numbers', label: 'WhatsApp Numbers', icon: PhoneOutgoing },
        { path: 'settings', url: '/business/settings', label: 'Settings', icon: Sliders },
      ];
    }
  };

  const menuItems = getSidebarItems();

  // Handle Mark notifications as read
  const markAllRead = () => {
    setNotifications(notifications.map(n => ({ ...n, read: true })));
    addToast("All notifications marked as read");
  };

  // Dynamic breadcrumb labels
  const getBreadcrumbs = () => {
    const pathLabels = {
      dashboard: 'Dashboard',
      businesses: 'Business Management',
      contacts: 'Contact Database',
      import: 'Import Wizard',
      groups: 'Contact Segmentation',
      templates: 'Message Templates',
      campaigns: 'Broadcast Campaigns',
      whatsapp_numbers: 'Connected Channels',
      settings: 'System Settings'
    };
    return [
      {label: currentRole === 'super_admin' ? 'Agency Login' : 'Business Login', path: 'dashboard'},
      { label: pathLabels[activePath] || 'Overview', path: activePath }
    ];
  };

  return (
    <div className="min-h-screen bg-[#F5F5F5] flex text-[#111111] overflow-hidden">

      {/* LEFT SIDEBAR (Dark Theme #111111) */}
      <aside className={`bg-[#111111] text-white flex flex-col transition-all duration-300 z-30 shrink-0 ${isSidebarOpen ? 'w-64' : 'w-20'
        } fixed h-[100vh] top-0 ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>

        {/* Sidebar Brand Header */}
        <div className="h-16 border-b border-white/10 flex items-center justify-between px-6">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 bg-white text-[#111111] font-extrabold flex items-center justify-center rounded-lg text-[18px]">
              O
            </div>
            {isSidebarOpen && (
              <span className="font-bold text-[18px] tracking-tight bg-gradient-to-r from-white to-gray-300 bg-clip-text text-transparent">
                Onella SaaS
              </span>
            )}
          </div>
          <button
            onClick={() => setIsSidebarOpen(!isSidebarOpen)}
            className="lg:hidden text-gray-400 hover:text-white"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Sidebar Nav Items */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto no-scrollbar">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activePath === item.path;
            return (
              <button
                key={item.path}
                onClick={() => {
                  navigate(item.url);
                  // Auto close on mobile
                  if (window.innerWidth < 1024) setIsSidebarOpen(false);
                }}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-150 group relative ${isActive
                    ? 'bg-white text-[#111111]'
                    : 'text-gray-400 hover:text-white hover:bg-white/5'
                  }`}
              >
                <div className="flex items-center gap-3">
                  <Icon className={`h-4.5 w-4.5 shrink-0 ${isActive ? 'text-[#111111]' : 'text-gray-400 group-hover:text-white'}`} />
                  {isSidebarOpen && <span>{item.label}</span>}
                </div>

                {/* Active Indicator Bar */}
                {isActive && !isSidebarOpen && (
                  <div className="absolute right-0 top-1/4 h-1/2 w-1 bg-white rounded-l" />
                )}

                {/* Badge Alert count */}
                {item.badge && isSidebarOpen && (
                  <span className="bg-[#DC2626] text-white text-[10px] font-bold px-2 py-0.5 rounded-full">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* Sidebar Footer Info */}
        <div className="p-4 border-t border-white/10 text-xs text-gray-500">
          {isSidebarOpen ? (
            <div className="flex items-center justify-between">
              <span>v1.0.0 Clickable</span>
              <kbd className="px-1.5 py-0.5 bg-white/10 rounded text-[10px] text-gray-400">Ctrl + K</kbd>
            </div>
          ) : (
            <span className="block text-center">•</span>
          )}
        </div>
      </aside>

      {/* MOBILE SIDEBAR BACKDROP */}
      {isSidebarOpen && (
        <div
          onClick={() => setIsSidebarOpen(false)}
          className="fixed inset-0 bg-black/50 lg:hidden z-20"
        />
      )}

      {/* MAIN CONTAINER */}
      <div className={`flex-1 flex flex-col min-w-0 relative transition-all duration-300 ${isSidebarOpen ? 'lg:pl-64' : 'lg:pl-20'
        }`}>

        {/* STICKY HEADER */}
        <header className="h-16 bg-white border-b border-[#E5E5E5] flex items-center justify-between px-6 sticky top-0 z-20 shadow-soft">

          {/* Left search and breadcrumbs */}
          <div className="flex items-center gap-4">
            <button
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className="text-[#6B7280] hover:text-[#111111]"
            >
              <Menu className="h-5 w-5" />
            </button>

          </div>

          {/* Right Header Controls */}
          <div className="flex items-center gap-4">

            {/* Notification Icon */}
            <div className="relative">
              <button
                onClick={() => {
                  setIsNotificationOpen(!isNotificationOpen);
                  setIsProfileOpen(false);
                }}
                className="p-2 rounded-custom hover:bg-[#F5F5F5] relative text-[#111111] transition-colors"
              >
                <Bell className="h-4.5 w-4.5" />
                {notifications.some(n => !n.read) && (
                  <span className="absolute top-1.5 right-1.5 h-2 w-2 bg-[#DC2626] rounded-full border border-white" />
                )}
              </button>

              {/* Notification Dropdown Panel */}
              {isNotificationOpen && (
                <div className="absolute right-0 mt-2 w-80 bg-white border border-[#E5E5E5] rounded-custom shadow-premium overflow-hidden z-40">
                  <div className="px-4 py-3 border-b border-[#E5E5E5] flex items-center justify-between bg-[#FAFAFA]">
                    <span className="text-xs font-bold text-[#111111]">Notifications</span>
                    <button
                      onClick={markAllRead}
                      className="text-[10px] font-semibold text-[#6B7280] hover:text-[#111111]"
                    >
                      Mark all read
                    </button>
                  </div>
                  <div className="max-h-60 overflow-y-auto divide-y divide-[#F5F5F5]">
                    {notifications.length > 0 ? (
                      notifications.map(item => (
                        <div
                          key={item.id}
                          className={`p-3.5 hover:bg-[#FAFAFA] transition-all ${!item.read ? 'bg-[#FAFAFA]/40 font-medium' : ''
                            }`}
                        >
                          <div className="flex items-start gap-2 justify-between">
                            <span className="text-xs text-[#111111] leading-relaxed">{item.body}</span>
                            {!item.read && <span className="h-1.5 w-1.5 bg-[#DC2626] rounded-full shrink-0 mt-1" />}
                          </div>
                          <span className="text-[10px] text-[#6B7280] mt-1 block">{item.time}</span>
                        </div>
                      ))
                    ) : (
                      <div className="p-6 text-center text-xs text-[#6B7280]">
                        No notifications
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* User Profile Dropdown Menu */}
            <div className="relative">
              <button
                onClick={() => {
                  setIsProfileOpen(!isProfileOpen);
                  setIsNotificationOpen(false);
                }}
                className="flex items-center gap-2 hover:opacity-90 transition-opacity"
              >
                <Avatar name={currentRole === 'super_admin' ? 'Agency Login' : 'Business Login'} size="sm" />
              </button>

              {isProfileOpen && (
                <div className="absolute right-0 mt-2 w-56 bg-white border border-[#E5E5E5] rounded-custom shadow-premium overflow-hidden z-40">
                  <div className="px-4 py-3 border-b border-[#E5E5E5]">
                    <p className="text-xs font-semibold text-[#111111]">
                      {currentRole === 'super_admin' ? 'Sarah Jenkins (Agency)' : 'Organic Grocers'}
                    </p>
                    <p className="text-[10px] text-[#6B7280] truncate mt-0.5">
                      {currentRole === 'super_admin' ? 'agency.admin@onella.com' : 'admin@grocers.com'}
                    </p>
                  </div>
                  <div className="p-1">
                    <button
                      onClick={() => {
                        setActivePath('settings');
                        setIsProfileOpen(false);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-[#111111] hover:bg-[#F5F5F5] rounded-lg text-left"
                    >
                      <User className="h-3.5 w-3.5 text-[#6B7280]" />
                      My Profile
                    </button>
                    <button
                      onClick={() => {
                        setIsProfileOpen(false);
                        setCurrentRole(currentRole === 'super_admin' ? 'business_admin' : 'super_admin');
                        setActivePath('dashboard');
                        addToast(`Switched Workspace Successfully!`);
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-[#111111] hover:bg-[#F5F5F5] rounded-lg text-left"
                    >
                      <ShieldAlert className="h-3.5 w-3.5 text-[#6B7280]" />
                      {currentRole === 'super_admin' ? 'Switch to Business Login' : 'Switch to Agency Login'}
                    </button>
                    <div className="border-t border-[#E5E5E5] my-1" />
                    <button
                      onClick={() => {
                        setIsProfileOpen(false);
                        logout();
                      }}
                      className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-[#DC2626] hover:bg-[#FFEBEE] rounded-lg text-left"
                    >
                      <LogOut className="h-3.5 w-3.5" />
                      Sign Out
                    </button>
                  </div>
                </div>
              )}
            </div>

          </div>
        </header>

        {/* BREADCRUMB BAR */}
        {(pathname === '/business-register' || pathname.startsWith('/business-details')) && (
          <div className="px-8 py-3 bg-white border-b border-[#E5E5E5] flex items-center gap-2 text-xs text-[#6B7280]">
            {getBreadcrumbs().map((b, index, arr) => (
              <React.Fragment key={index}>
                <span
                  className={`hover:text-[#111111] cursor-pointer transition-colors ${index === arr.length - 1 ? 'text-[#111111] font-semibold' : ''
                    }`}
                  onClick={() => {
                    if (b.path === 'dashboard') {
                      navigate(currentRole === 'super_admin' ? '/super-admin/dashboard' : '/business/dashboard');
                    } else if (b.path === 'businesses') {
                      navigate('/business-listing');
                    } else {
                      const matchedItem = menuItems.find(item => item.path === b.path);
                      if (matchedItem) navigate(matchedItem.url);
                    }
                  }}
                >
                  {b.label}
                </span>
                {index < arr.length - 1 && <span className="text-[10px] text-[#E5E5E5]">/</span>}
              </React.Fragment>
            ))}
          </div>
        )}

        {/* MAIN CONTENT PORT (Scrollable) */}
        <main className="flex-1 overflow-y-auto p-8 max-w-[1400px] mx-auto w-full">
          {children}
        </main>

      </div>
    </div>
  );
};
