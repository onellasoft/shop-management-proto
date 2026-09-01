import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { logout as apiLogout, refreshTokens } from '../lib/api';
import bizData from '../mock/businesses.json';
import tplData from '../mock/templates.json';
import contactsData from '../mock/contacts.json';
import campaignsData from '../mock/messages.json';
import msgData from '../mock/messages.json';

// ---------------------------------------------------------------------------
// Role constants — single source of truth, driven by backend values
// ---------------------------------------------------------------------------
export const ROLES = {
  SUPERADMIN: 'superadmin',
  AGENCYADMIN: 'agencyadmin',
  CUSTOMERADMIN: 'customeradmin',
};

/** Returns true if the role has super-admin scope (platform-wide views). */
export const isSuperAdmin = (role) => role === ROLES.SUPERADMIN;

/** Returns true if the role has agency-level scope. */
export const isAgencyAdmin = (role) => role === ROLES.AGENCYADMIN;

// ---------------------------------------------------------------------------
// JWT helpers (no library dependency — backend JWTs are standard)
// ---------------------------------------------------------------------------

/** Decode JWT payload without verifying the signature (verification is server-side). */
function decodeJwtPayload(token) {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(atob(base64));
  } catch {
    return null;
  }
}

/** Return true if the access token is expired (or undecodable). */
function isTokenExpired(token) {
  const payload = decodeJwtPayload(token);
  if (!payload?.exp) return true;
  // Give a 30-second buffer so we refresh before the server rejects it.
  return Date.now() / 1000 >= payload.exp - 30;
}

// ---------------------------------------------------------------------------
// localStorage helpers
// ---------------------------------------------------------------------------
const LS_ACCESS  = 'onella_access';
const LS_REFRESH = 'onella_refresh';

function loadTokens() {
  return {
    accessToken:  localStorage.getItem(LS_ACCESS)  ?? null,
    refreshToken: localStorage.getItem(LS_REFRESH) ?? null,
  };
}

function saveTokens(access, refresh) {
  localStorage.setItem(LS_ACCESS,  access);
  localStorage.setItem(LS_REFRESH, refresh);
}

function clearTokens() {
  localStorage.removeItem(LS_ACCESS);
  localStorage.removeItem(LS_REFRESH);
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const AppContext = createContext();

export const AppProvider = ({ children }) => {
  const location  = useLocation();
  const navigate  = useNavigate();
  const pathname  = location.pathname;

  // ------------------------------------------------------------------
  // Auth state
  // ------------------------------------------------------------------
  const [accessToken,  setAccessToken]  = useState(null);
  const [refreshToken, setRefreshToken] = useState(null);
  // userInfo holds decoded JWT payload: { sub, email, role_type, agency_id, customer_id }
  const [userInfo, setUserInfo] = useState(null);
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authLoading, setAuthLoading] = useState(true); // true while we try silent refresh on mount

  /** Derive the current role directly from the JWT claim. */
  const currentRole = userInfo?.role_type ?? null;

  /** Allow runtime role override (e.g. the workspace-switch button). Kept for
   *  UI convenience; the JWT still governs what the backend will authorise. */
  const [roleOverride, setRoleOverride] = useState(null);
  const effectiveRole = roleOverride ?? currentRole;

  // setCurrentRole — called by the workspace-switch button; cycles between
  // superadmin and agencyadmin views in the UI.
  const setCurrentRole = useCallback((role) => {
    setRoleOverride(role);
  }, []);

  /** Apply a full TokenPair from the backend to state + localStorage. */
  const applyTokenPair = useCallback((pair) => {
    const { access_token, refresh_token } = pair;
    saveTokens(access_token, refresh_token);
    setAccessToken(access_token);
    setRefreshToken(refresh_token);
    setUserInfo(decodeJwtPayload(access_token));
    setRoleOverride(null); // reset any manual override on fresh login
    setIsAuthenticated(true);
  }, []);

  // ------------------------------------------------------------------
  // Silent refresh on mount — restore session if tokens are in localStorage
  // ------------------------------------------------------------------
  useEffect(() => {
    const { accessToken: storedAccess, refreshToken: storedRefresh } = loadTokens();

    async function tryRestore() {
      if (!storedRefresh) {
        setAuthLoading(false);
        return;
      }

      // If the stored access token is still valid, use it directly.
      if (storedAccess && !isTokenExpired(storedAccess)) {
        setAccessToken(storedAccess);
        setRefreshToken(storedRefresh);
        setUserInfo(decodeJwtPayload(storedAccess));
        setIsAuthenticated(true);
        setAuthLoading(false);
        return;
      }

      // Access token expired — attempt silent refresh.
      try {
        const pair = await refreshTokens(storedRefresh);
        applyTokenPair(pair);
      } catch {
        // Refresh token also invalid/expired — clear and go to login.
        clearTokens();
      } finally {
        setAuthLoading(false);
      }
    }

    tryRestore();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Auth actions exposed to children
  // ------------------------------------------------------------------

  /** Called after a successful login (email/pass or OTP). */
  const handleLoginSuccess = useCallback((tokenPair) => {
    applyTokenPair(tokenPair);
    const role = decodeJwtPayload(tokenPair.access_token)?.role_type;
    navigate(role === ROLES.SUPERADMIN ? '/super-admin/dashboard' : '/business/dashboard');
  }, [applyTokenPair, navigate]);

  const logout = useCallback(async () => {
    const rt = refreshToken ?? loadTokens().refreshToken;
    if (rt) {
      try { await apiLogout(rt); } catch { /* ignore — clear locally regardless */ }
    }
    clearTokens();
    setAccessToken(null);
    setRefreshToken(null);
    setUserInfo(null);
    setRoleOverride(null);
    setIsAuthenticated(false);
    addToast('Logged out successfully.');
    navigate('/login');
  }, [refreshToken]); // eslint-disable-line react-hooks/exhaustive-deps

  // ------------------------------------------------------------------
  // Navigation helpers
  // ------------------------------------------------------------------
  const getActivePathFromPathname = (path) => {
    if (path.startsWith('/super-admin/dashboard')) return 'dashboard';
    if (path.startsWith('/business/dashboard'))    return 'dashboard';
    if (path.startsWith('/business-listing') || path.startsWith('/business-register') || path.startsWith('/business-details')) return 'businesses';
    if (path.startsWith('/super-admin/settings'))  return 'settings';
    if (path.startsWith('/contacts'))              return 'contacts';
    if (path.startsWith('/import'))                return 'import';
    if (path.startsWith('/groups'))                return 'groups';
    if (path.startsWith('/templates'))             return 'templates';
    if (path.startsWith('/campaigns'))             return 'campaigns';
    if (path.startsWith('/whatsapp-numbers'))       return 'whatsapp_numbers';
    if (path.startsWith('/business/settings'))     return 'settings';
    return 'dashboard';
  };

  const activePath = getActivePathFromPathname(pathname);

  const setActivePath = (path) => {
    if (isSuperAdmin(effectiveRole)) {
      const paths = {
        dashboard: '/super-admin/dashboard',
        businesses: '/business-listing',
        settings: '/super-admin/settings',
      };
      if (paths[path]) navigate(paths[path]);
    } else {
      const paths = {
        dashboard: '/business/dashboard',
        contacts: '/contacts',
        import: '/import',
        groups: '/groups',
        templates: '/templates',
        campaigns: '/campaigns',
        whatsapp_numbers: '/whatsapp-numbers',
        settings: '/business/settings',
      };
      if (paths[path]) navigate(paths[path]);
    }
  };

  // ------------------------------------------------------------------
  // Toast
  // ------------------------------------------------------------------
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [toasts, setToasts] = useState([]);

  const addToast = (message, type = 'success') => {
    const id = Math.random().toString(36).substring(7);
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };

  // ------------------------------------------------------------------
  // Mock data (unchanged until Track 2)
  // ------------------------------------------------------------------
  const [businesses, setBusinesses] = useState([]);
  const [templates,  setTemplates]  = useState([]);
  const [contacts,   setContacts]   = useState([]);
  const [campaigns,  setCampaigns]  = useState([]);
  const [messages,   setMessages]   = useState([]);
  const [groups, setGroups] = useState([
    { id: 'grp_1', name: 'VIP Customers',  membersCount: 45  },
    { id: 'grp_2', name: 'New Signups',    membersCount: 82  },
    { id: 'grp_3', name: 'All Retailers',  membersCount: 120 },
    { id: 'grp_4', name: 'B2B Clients',    membersCount: 34  },
  ]);
  const [whatsappNumbers, setWhatsappNumbers] = useState([
    { id: 'num_1', phone: '+91 99999 88888', name: 'Primary Business Desk', status: 'Connected'    },
    { id: 'num_2', phone: '+91 99999 77777', name: 'Support Line',          status: 'Connected'    },
    { id: 'num_3', phone: '+91 98888 66666', name: 'Sales Outreach',        status: 'Disconnected' },
  ]);
  const [notifications, setNotifications] = useState([
    { id: 'not_2', title: 'Critical Storage Limit', body: "Organic Grocers reached 85% of their storage quota", time: '1 hour ago',  read: false, role: ROLES.SUPERADMIN    },
    { id: 'not_3', title: 'Campaign Completed',     body: 'EID Mubarak Promo campaign completed successfully',   time: '3 hours ago', read: false, role: ROLES.AGENCYADMIN  },
    { id: 'not_4', title: 'WhatsApp Disconnected',  body: 'Sales Outreach number was disconnected',              time: '1 day ago',   read: true,  role: ROLES.AGENCYADMIN  },
  ]);

  // Inflate mock data on mount (unchanged from original)
  useEffect(() => {
    let bList = [...bizData];
    const owners     = ['Arvind','Meenakshi','Sanjay','Suresh','Vikram','Shalini','Sunita','Deepak','Mohan','Amit'];
    const shopNames  = ['Mega Mart','Classic Shoes','National Stationers','Pioneer Chemist','Super Bakers','Kolkata Sweets','Metro Hardware','City Plaza','Smart Wear','Digital Hub'];
    const statuses   = ['Active','Suspended'];
    const cities     = ['Mumbai','Delhi','Bangalore','Kolkata','Chennai','Pune','Hyderabad','Ahmedabad','Jaipur','Lucknow'];
    for (let i = bList.length + 1; i <= 50; i++) {
      const ownerName = owners[i % owners.length] + ' ' + ['Sen','Patel','Reddy','Nair','Joshi','Roy','Bose','Dutta'][i % 8];
      const name      = shopNames[i % shopNames.length] + ' ' + i;
      bList.push({
        id: `biz_${i}`, name, owner: ownerName,
        mobile: `+91 98${i%10}${i%10}0 123${i%10}`,
        email: `contact@${name.toLowerCase().replace(/\s+/g,'')}.com`,
        status: statuses[i%statuses.length],
        createdDate: `2025-05-${(i%28)+1}`,
        logo: name.split(' ').map(w=>w[0]).join('').substring(0,2),
        gst: `27GGGGG${1000+i}A1Z${i%9}`, pan: `PANBI${1000+i}A`,
        address: `Shop ${10+i}, Commercial Arcade, ${cities[i%cities.length]}`,
        usage: { storageUsed: parseFloat((Math.random()*20).toFixed(1)), messagesSent: Math.floor(Math.random()*5000), whatsappAccountsConnected: Math.floor(Math.random()*3)+1 },
      });
    }
    setBusinesses(bList);

    let cList = [...contactsData];
    const citiesList = ['Mumbai','Delhi','Bangalore','Hyderabad','Pune','Kolkata','Chennai','Ahmedabad','Gurugram','Chandigarh'];
    const tagList    = [['VIP'],['Regular'],['New Lead'],['Retailer'],['Wholesaler'],['VIP','Regular'],['Loyal']];
    const firstNames = ['Rahul','Amit','Pooja','Vikram','Sneha','Karan','Simran','Preity','Sachin','Virat','Rohit','Jasprit','Hardik','Rishabh','Shreyas','Yuzvendra','Ravindra','MS','Sourav','Rahul'];
    const lastNames  = ['Kumar','Sharma','Singh','Patel','Reddy','Nair','Das','Joshi','Gupta','Rao','Devi','Prasad','Varma','Mishra','Yadav','Choudhary','Dutta','Sen','Bose','Mehta'];
    for (let i = cList.length + 1; i <= 200; i++) {
      const fName = firstNames[i%firstNames.length]; const lName = lastNames[(i+3)%lastNames.length];
      cList.push({ id:`c_${i}`, name:`${fName} ${lName}`, mobile:`+91 9${i%10}${i%10}00 88${i%100}`, email:`${fName.toLowerCase()}.${lName.toLowerCase()}${i}@gmail.com`, city:citiesList[i%citiesList.length], tags:tagList[i%tagList.length], status:i%15===0?'Inactive':'Active' });
    }
    setContacts(cList);

    let tList = [...tplData];
    const categories = ['Marketing','Utility','Authentication'];
    const words = ['summer_deal','invoice_alert','shipping_update','account_otp','refund_confirm','holiday_greeting','flash_offer','survey_link','service_remind','membership_renew'];
    for (let i = tList.length + 1; i <= 30; i++) {
      const name = words[i%words.length]+'_'+i; const cat = categories[i%categories.length];
      tList.push({ id:`tpl_${i}`, name, category:cat, language:'English (US)', status:i%7===0?'Pending':i%11===0?'Rejected':'Approved', body:`Hello {{name}}, this is a template message for ${name.replace(/_/g,' ')}. Use reference code {{code}} for actions.`, variables:['name','code'], lastModified:`2025-06-${(i%25)+1}` });
    }
    setTemplates(tList);

    let cpList = [...(campaignsData ?? [])];
    for (let i = cpList.length + 1; i <= 20; i++) {
      const template = tList[i%tList.length];
      const sent = Math.floor(Math.random()*500)+50; const delivered = Math.floor(sent*0.95); const read = Math.floor(delivered*0.85);
      cpList.push({ id:`cmp_${i}`, name:`Campaign ${i}`, template:template.name, group:['VIP Customers','New Signups','All Retailers','B2B Clients'][i%4], status:i%4===0?'Draft':i%5===0?'Scheduled':'Completed', scheduledDate:`2025-06-${(i%15)+10} 11:00 AM`, sentCount:i%4===0?0:sent, delivered:i%4===0?0:delivered, read:i%4===0?0:read, failed:i%4===0?0:sent-delivered });
    }
    setCampaigns(cpList);

    let mList = [...msgData];
    const statusesList = ['Read','Delivered','Failed','Sent'];
    for (let i = mList.length + 1; i <= 100; i++) {
      const contact = cList[i%cList.length]; const template = tList[i%tList.length];
      mList.push({ id:`msg_${i}`, contactName:contact.name, mobile:contact.mobile, templateName:template.name, status:statusesList[i%statusesList.length], timestamp:`2025-06-${(i%5)+25} 0${(i%8)+1}:${i%60<10?'0'+(i%60):i%60} ${i%2===0?'AM':'PM'}` });
    }
    setMessages(mList);
  }, []);

  // ------------------------------------------------------------------
  // Mock CRUD actions (unchanged until Track 2)
  // ------------------------------------------------------------------
  const addBusiness = (biz) => {
    const newBiz = { ...biz, id:`biz_${businesses.length+1}`, logo:biz.name.split(' ').map(w=>w[0]).join('').substring(0,2), createdDate:new Date().toISOString().split('T')[0], usage:{ storageUsed:0, messagesSent:0, whatsappAccountsConnected:1 } };
    setBusinesses([newBiz, ...businesses]);
    addToast(`Business "${biz.name}" created successfully!`);
  };
  const updateBusiness = (id, updatedFields) => { setBusinesses(businesses.map(b => b.id===id ? {...b,...updatedFields} : b)); addToast('Business updated successfully!'); };
  const suspendBusiness = (id) => {
    setBusinesses(businesses.map(b => {
      if (b.id!==id) return b;
      const newStatus = b.status==='Suspended' ? 'Active' : 'Suspended';
      addToast(`Business "${b.name}" ${newStatus==='Suspended'?'suspended':'activated'} successfully!`);
      return {...b, status:newStatus};
    }));
  };
  const addContact = (contact) => { const nc = {...contact, id:`c_${contacts.length+1}`, status:'Active'}; setContacts([nc,...contacts]); addToast(`Contact "${contact.name}" added successfully!`); };
  const deleteContact = (id) => { setContacts(contacts.filter(c=>c.id!==id)); addToast('Contact deleted successfully!'); };
  const importContacts = (importedList) => { const formatted = importedList.map((c,i)=>({...c, id:`c_${contacts.length+i+1}`, status:'Active'})); setContacts([...formatted,...contacts]); addToast(`Successfully imported ${importedList.length} contacts!`); };
  const addGroup = (groupName) => { setGroups([...groups, { id:`grp_${groups.length+1}`, name:groupName, membersCount:0 }]); addToast(`Group "${groupName}" created successfully!`); };
  const deleteGroup = (id) => { setGroups(groups.filter(g=>g.id!==id)); addToast('Group deleted successfully!'); };
  const addTemplate = (tpl) => { const nt = {...tpl, id:`tpl_${templates.length+1}`, status:'Approved', lastModified:new Date().toISOString().split('T')[0]}; setTemplates([nt,...templates]); addToast(`Template "${tpl.name}" submitted successfully!`); };
  const deleteTemplate = (id) => { setTemplates(templates.filter(t=>t.id!==id)); addToast('Template deleted successfully!'); };
  const startCampaign = (camp) => {
    const nc = { id:`cmp_${campaigns.length+1}`, name:camp.name, template:camp.template, group:camp.group, status:camp.schedule==='Immediate'?'Completed':'Scheduled', scheduledDate:camp.schedule==='Immediate'?'Just Now':camp.scheduledTime, sentCount:camp.schedule==='Immediate'?120:0, delivered:camp.schedule==='Immediate'?118:0, read:camp.schedule==='Immediate'?104:0, failed:camp.schedule==='Immediate'?2:0 };
    setCampaigns([nc,...campaigns]);
    addToast(`Campaign "${camp.name}" started successfully!`);
    if (camp.schedule==='Immediate') {
      const newMsgs = [
        { id:`msg_sim_${Math.random()}`, contactName:'Rahul Sharma', mobile:'+91 98000 11111', templateName:camp.template, status:'Read', timestamp:'Just Now' },
        { id:`msg_sim_${Math.random()}`, contactName:'Sneha Patil',  mobile:'+91 98000 22222', templateName:camp.template, status:'Read', timestamp:'Just Now' },
        { id:`msg_sim_${Math.random()}`, contactName:'Anil Nair',    mobile:'+91 98000 33333', templateName:camp.template, status:'Delivered', timestamp:'Just Now' },
      ];
      setMessages([...newMsgs, ...messages]);
    }
  };

  // ------------------------------------------------------------------
  // Context value
  // ------------------------------------------------------------------
  return (
    <AppContext.Provider value={{
      // auth
      isAuthenticated,
      authLoading,
      accessToken,
      refreshToken,
      userInfo,
      handleLoginSuccess,
      logout,
      // role
      currentRole: effectiveRole,
      setCurrentRole,
      // navigation
      activePath,
      setActivePath,
      // ui
      isCommandPaletteOpen,
      setIsCommandPaletteOpen,
      toasts,
      addToast,
      // data
      businesses,   addBusiness,    updateBusiness, suspendBusiness,
      contacts,     addContact,     deleteContact,  importContacts,
      groups,       addGroup,       deleteGroup,
      templates,    addTemplate,    deleteTemplate,
      campaigns,    startCampaign,
      messages,
      whatsappNumbers,
      notifications,
      setNotifications,
    }}>
      {children}
    </AppContext.Provider>
  );
};

export const useApp = () => useContext(AppContext);
