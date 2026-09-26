import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useApp, isAgencyAdmin, isSuperAdmin } from '../context/AppContext';
import { DataTable } from '../components/DataTable';
import { Badge, Button, Input } from '../components/UI';
import { Modal, ConfirmDialog } from '../components/Modal';
import { AgencyMultiSelect } from '../components/AgencyMultiSelect';
import { FiPlus, FiEye, FiChevronLeft, FiClock, FiTrash2, FiCheck, FiChevronRight, FiBriefcase, FiCheckCircle, FiAlertTriangle, FiSend, FiEdit } from 'react-icons/fi';

export const BusinessManagement = () => {
  const { businesses, agencies, addBusiness, updateBusiness, suspendBusiness, currentRole, userInfo } = useApp();
  const location = useLocation();
  const navigate = useNavigate();

  // Superadmin agency filter: empty array = "All Agencies" (show everything).
  const [selectedAgencyIds, setSelectedAgencyIds] = useState([]);

  // An agencyadmin only sees the businesses belonging to their agency; a
  // superadmin sees every business, optionally narrowed to the agencies they
  // pick in the multi-select.
  const scopedBusinesses = React.useMemo(() => {
    if (isAgencyAdmin(currentRole)) {
      const agencyId = userInfo?.agency_id ?? null;
      return businesses.filter(b => b.agencyId === agencyId);
    }
    if (isSuperAdmin(currentRole) && selectedAgencyIds.length > 0) {
      return businesses.filter(b => selectedAgencyIds.includes(b.agencyId));
    }
    return businesses;
  }, [businesses, currentRole, userInfo, selectedAgencyIds]);

  const [editingBizId, setEditingBizId] = useState(null);
  const view = location.pathname === '/business-register' ? 'new' : (editingBizId ? 'edit' : 'list');
  const [confirmStatusChange, setConfirmStatusChange] = useState({
    isOpen: false,
    businessId: null,
    businessName: '',
    isSuspended: false
  });
  const [logsModal, setLogsModal] = useState({
    isOpen: false,
    business: null
  });
  const [tempLogoUrl, setTempLogoUrl] = useState(null);
  const [isCropping, setIsCropping] = useState(false);
  const [currentStep, setCurrentStep] = useState(1);
  const [newBiz, setNewBiz] = useState({
    customerType: 'Business',
    salutation: 'Mr.',
    firstName: '',
    lastName: '',
    name: '',
    displayName: '',
    email: '',
    workPhoneCode: '+91',
    workPhone: '',
    mobilePhoneCode: '+91',
    mobile: '',
    language: 'English',
    gstTreatment: 'Registered Business - Composition',
    gst: '',
    legalName: '',
    tradeName: '',
    placeOfSupply: 'Maharashtra',
    pan: '',
    taxPreference: 'Taxable',
    currency: 'INR',
    openingBalance: '',
    paymentTerms: 'Due on Receipt',
    enablePortal: false,
    billingAttention: '',
    billingCountry: 'India',
    billingStreet1: '',
    billingStreet2: '',
    billingCity: '',
    billingState: 'Maharashtra',
    billingPinCode: '',
    billingPhoneCode: '+91',
    billingPhone: '',
    billingPhones: [''],
    billingPhoneCodes: ['+91'],
    billingFax: '',
    shippingAttention: '',
    shippingCountry: 'India',
    shippingStreet1: '',
    shippingStreet2: '',
    shippingCity: '',
    shippingState: 'Maharashtra',
    shippingPinCode: '',
    shippingPhoneCode: '+91',
    shippingPhone: '',
    shippingFax: '',
    contactPersons: [],
    status: 'Active',
    logoUrl: null,
    selectedModules: ['bulk_message'],
    bulkMessagePlan: 'free'
  });

  const resetForm = () => {
    setNewBiz({
      customerType: 'Business',
      salutation: 'Mr.',
      firstName: '',
      lastName: '',
      name: '',
      displayName: '',
      email: '',
      workPhoneCode: '+91',
      workPhone: '',
      mobilePhoneCode: '+91',
      mobile: '',
      language: 'English',
      gstTreatment: 'Registered Business - Composition',
      gst: '',
      legalName: '',
      tradeName: '',
      placeOfSupply: 'Maharashtra',
      pan: '',
      taxPreference: 'Taxable',
      currency: 'INR',
      openingBalance: '',
      paymentTerms: 'Due on Receipt',
      enablePortal: false,
      billingAttention: '',
      billingCountry: 'India',
      billingStreet1: '',
      billingStreet2: '',
      billingCity: '',
      billingState: 'Maharashtra',
      billingPinCode: '',
      billingPhoneCode: '+91',
      billingPhone: '',
      billingPhones: [''],
      billingPhoneCodes: ['+91'],
      billingFax: '',
      shippingAttention: '',
      shippingCountry: 'India',
      shippingStreet1: '',
      shippingStreet2: '',
      shippingCity: '',
      shippingState: 'Maharashtra',
      shippingPinCode: '',
      shippingPhoneCode: '+91',
      shippingPhone: '',
      shippingFax: '',
      contactPersons: [],
      status: 'Active',
      logoUrl: null,
      selectedModules: ['bulk_message'],
      bulkMessagePlan: 'free'
    });
    setTempLogoUrl(null);
    setIsCropping(false);
    setFormErrors({});
    setCurrentStep(1);
  };

  const [formErrors, setFormErrors] = useState({});

  React.useEffect(() => {
    if (location.pathname === '/business-register') {
      resetForm();
      setEditingBizId(null);
    }
  }, [location.pathname]);

  const handleEditClick = (row) => {
    const ownerParts = (row.owner || '').split(' ');
    let salutation = 'Mr.';
    let firstName = '';
    let lastName = '';
    if (ownerParts.length > 0) {
      if (['Mr.', 'Mrs.', 'Ms.', 'Dr.'].includes(ownerParts[0])) {
        salutation = ownerParts[0];
        firstName = ownerParts[1] || '';
        lastName = ownerParts.slice(2).join(' ') || '';
      } else {
        firstName = ownerParts[0];
        lastName = ownerParts.slice(1).join(' ') || '';
      }
    }

    const mobileParts = (row.mobile || '').split(' ');
    let mobilePhoneCode = '+91';
    let mobile = row.mobile || '';
    if (mobileParts.length > 1) {
      mobilePhoneCode = mobileParts[0];
      mobile = mobileParts.slice(1).join('').replace(/\s+/g, '');
    }

    const addressParts = (row.address || '').split(',').map(s => s.trim());
    let billingStreet1 = row.billingStreet1 || '';
    let billingStreet2 = row.billingStreet2 || '';
    let billingCity = row.billingCity || '';
    let billingState = row.billingState || 'Maharashtra';
    let billingPinCode = row.billingPinCode || '';

    if (!billingStreet1 && addressParts.length > 0) {
      if (addressParts.length >= 4) {
        billingStreet1 = addressParts[0];
        billingStreet2 = addressParts.slice(1, addressParts.length - 3).join(', ');
        billingCity = addressParts[addressParts.length - 3];
        billingState = addressParts[addressParts.length - 2];
        const lastPart = addressParts[addressParts.length - 1];
        if (/\d{6}/.test(lastPart)) {
          billingPinCode = lastPart.match(/\d{6}/)[0];
        }
      } else if (addressParts.length === 3) {
        billingStreet1 = addressParts[0];
        billingCity = addressParts[1];
        billingState = addressParts[2];
      } else {
        billingStreet1 = row.address || '';
      }
    }

    setEditingBizId(row.id);
    setNewBiz({
      customerType: row.customerType || 'Business',
      salutation: row.salutation || salutation,
      firstName: row.firstName || firstName,
      lastName: row.lastName || lastName,
      name: row.name || '',
      displayName: row.displayName || row.name || '',
      email: row.email || '',
      workPhoneCode: row.workPhoneCode || '+91',
      workPhone: row.workPhone || '',
      mobilePhoneCode: row.mobilePhoneCode || mobilePhoneCode,
      mobile: mobile,
      language: row.language || 'English',
      gstTreatment: row.gstTreatment || 'Registered Business - Composition',
      gst: row.gst || '',
      legalName: row.legalName || row.name || '',
      tradeName: row.tradeName || row.name || '',
      placeOfSupply: row.placeOfSupply || 'Maharashtra',
      pan: row.pan || '',
      taxPreference: row.taxPreference || 'Taxable',
      currency: row.currency || 'INR',
      openingBalance: row.openingBalance || '',
      paymentTerms: row.paymentTerms || 'Due on Receipt',
      enablePortal: row.enablePortal || false,
      billingAttention: row.billingAttention || '',
      billingCountry: row.billingCountry || 'India',
      billingStreet1: billingStreet1,
      billingStreet2: billingStreet2,
      billingCity: billingCity,
      billingState: billingState,
      billingPinCode: billingPinCode,
      billingPhoneCode: row.billingPhoneCode || '+91',
      billingPhone: row.billingPhone || '',
      billingPhones: row.billingPhones || [mobile],
      billingPhoneCodes: row.billingPhoneCodes || ['+91'],
      billingFax: row.billingFax || '',
      shippingAttention: row.shippingAttention || '',
      shippingCountry: row.shippingCountry || 'India',
      shippingStreet1: row.shippingStreet1 || '',
      shippingStreet2: row.shippingStreet2 || '',
      shippingCity: row.shippingCity || '',
      shippingState: row.shippingState || 'Maharashtra',
      shippingPinCode: row.shippingPinCode || '',
      shippingPhoneCode: row.shippingPhoneCode || '+91',
      shippingPhone: row.shippingPhone || '',
      shippingFax: row.shippingFax || '',
      contactPersons: row.contactPersons || [],
      status: row.status || 'Active',
      logoUrl: row.logoUrl || null,
      selectedModules: row.selectedModules || ['bulk_message'],
      bulkMessagePlan: row.bulkMessagePlan || 'free'
    });
    setCurrentStep(1);
  };

  // Validate fields for a specific step
  const validateStep = (step) => {
    const errs = {};
    if (step === 1) {
      if (!newBiz.firstName.trim()) {
        errs.firstName = "First Name is required.";
      }
      if (!newBiz.lastName.trim()) {
        errs.lastName = "Last Name is required.";
      }
      if (!newBiz.displayName.trim()) {
        errs.displayName = "Display Name is required.";
      }
      if (newBiz.customerType === 'Business') {
        if (!newBiz.name.trim()) {
          errs.name = "Company Name is required.";
        }
      }
      if (!newBiz.mobile && !newBiz.workPhone) {
        errs.mobile = "At least one contact number is required.";
      }
      if (newBiz.mobile && newBiz.mobile.length !== 10) {
        errs.mobile = "Mobile number must be exactly 10 digits.";
      }
      if (newBiz.workPhone && newBiz.workPhone.length !== 10) {
        errs.workPhone = "Work phone must be exactly 10 digits.";
      }
      if (newBiz.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(newBiz.email)) {
        errs.email = "Please enter a valid email address.";
      }
    } else if (step === 2) {
      if (newBiz.customerType === 'Business' && newBiz.gstTreatment.startsWith('Registered')) {
        if (!newBiz.gst.trim()) {
          errs.gst = "GSTIN is required for registered business.";
        } else if (!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(newBiz.gst)) {
          errs.gst = "Invalid GSTIN format (e.g. 27AAAAA1111A1Z1).";
        }
      }
      if (newBiz.pan && !/^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test(newBiz.pan)) {
        errs.pan = "Invalid PAN format (e.g. ABCDE1234F).";
      }
    } else if (step === 3) {
      if (!newBiz.billingStreet1.trim()) {
        errs.billingStreet1 = "Street 1 is required.";
      }
      if (!newBiz.billingStreet2.trim()) {
        errs.billingStreet2 = "Street 2 is required.";
      }
      if (!newBiz.billingCountry.trim()) {
        errs.billingCountry = "Country is required.";
      }
      if (!newBiz.billingState.trim()) {
        errs.billingState = "State is required.";
      }
      if (!newBiz.billingCity.trim()) {
        errs.billingCity = "City is required.";
      } else if (/\d/.test(newBiz.billingCity)) {
        errs.billingCity = "City cannot contain numbers.";
      }
      if (!newBiz.billingPinCode.trim()) {
        errs.billingPinCode = "Pin Code is required.";
      } else if (newBiz.billingPinCode.replace(/\D/g, '').length !== 6) {
        errs.billingPinCode = "Pin Code must be exactly 6 digits.";
      }
      if (!newBiz.billingPhones || !newBiz.billingPhones[0] || !newBiz.billingPhones[0].trim()) {
        errs.billingPhones = "Primary phone number is required.";
      } else if (newBiz.billingPhones[0].length !== 10) {
        errs.billingPhones = "Phone number must be exactly 10 digits.";
      }
      if (newBiz.billingPhones && newBiz.billingPhones[1] && newBiz.billingPhones[1].trim() && newBiz.billingPhones[1].length !== 10) {
        errs.billingPhones2 = "Secondary phone number must be exactly 10 digits.";
      }
    }
    setFormErrors(errs);
    return Object.keys(errs).length === 0;
  };

  // Check if current step is fully valid (all required fields filled & valid formats)
  const isStepValid = (step) => {
    if (step === 1) {
      if (!newBiz.firstName.trim()) return false;
      if (!newBiz.lastName.trim()) return false;
      if (!newBiz.displayName.trim()) return false;
      if (newBiz.customerType === 'Business' && !newBiz.name.trim()) return false;
      if (!newBiz.mobile && !newBiz.workPhone) return false;
      if (newBiz.mobile && newBiz.mobile.length !== 10) return false;
      if (newBiz.workPhone && newBiz.workPhone.length !== 10) return false;
      if (newBiz.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(newBiz.email)) return false;
      return true;
    }
    if (step === 2) {
      if (newBiz.customerType === 'Business' && newBiz.gstTreatment.startsWith('Registered')) {
        if (!newBiz.gst.trim()) return false;
        if (!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(newBiz.gst)) return false;
      }
      if (newBiz.pan && !/^[A-Z]{5}[0-9]{4}[A-Z]{1}$/.test(newBiz.pan)) return false;
      return true;
    }
    if (step === 3) {
      if (!newBiz.billingStreet1 || !newBiz.billingStreet1.trim()) return false;
      if (!newBiz.billingStreet2 || !newBiz.billingStreet2.trim()) return false;
      if (!newBiz.billingCountry || !newBiz.billingCountry.trim()) return false;
      if (!newBiz.billingState || !newBiz.billingState.trim()) return false;
      if (!newBiz.billingCity || !newBiz.billingCity.trim() || /\d/.test(newBiz.billingCity)) return false;
      if (!newBiz.billingPinCode || newBiz.billingPinCode.replace(/\D/g, '').length !== 6) return false;
      if (!newBiz.billingPhones || !newBiz.billingPhones[0] || !newBiz.billingPhones[0].trim()) return false;
      if (newBiz.billingPhones[0].length !== 10) return false;
      if (newBiz.billingPhones[1] && newBiz.billingPhones[1].trim() && newBiz.billingPhones[1].length !== 10) return false;
      return true;
    }
    if (step === 4 && newBiz.customerType === 'Business') {
      return newBiz.contactPersons.every(cp =>
        cp.firstName.trim() !== '' &&
        cp.lastName.trim() !== '' &&
        (!cp.email || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cp.email)) &&
        cp.mobile.replace(/\D/g, '').length === 10
      );
    }
    return true;
  };

  // Filters State
  const [statusFilter, setStatusFilter] = useState('All');

  // Handle Form Submission
  const handleSubmit = (e) => {
    if (e) e.preventDefault();

    // Perform final check of all relevant steps
    const isStep1Valid = validateStep(1);
    if (!isStep1Valid) {
      setCurrentStep(1);
      return;
    }

    const isStep2Valid = validateStep(2);
    if (!isStep2Valid) {
      setCurrentStep(2);
      return;
    }

    const formattedBiz = {
      ...newBiz,
      name: newBiz.name || newBiz.displayName || 'Unnamed Store',
      owner: `${newBiz.salutation} ${newBiz.firstName} ${newBiz.lastName}`.trim() || 'No Owner Name',
      mobile: `${newBiz.mobilePhoneCode} ${newBiz.mobile || newBiz.workPhone}`.trim(),
      email: newBiz.email || 'no-email@store.com',
      address: `${newBiz.billingStreet1}, ${newBiz.billingCity}, ${newBiz.billingState}`.trim() || 'No Address Provided',
    };

    if (view === 'edit') {
      updateBusiness(editingBizId, formattedBiz);
      setEditingBizId(null);
    } else {
      addBusiness(formattedBiz);
      navigate('/business-listing');
    }
    resetForm();
  };

  // Filter businesses (already scoped to the agency for agencyadmin)
  const filteredData = React.useMemo(() => {
    return scopedBusinesses.filter(b => {
      const matchStatus = statusFilter === 'All' || b.status === statusFilter;
      return matchStatus;
    });
  }, [scopedBusinesses, statusFilter]);

  // Table Column Definitions
  const columns = [
    {
      key: 'name',
      title: 'Business Name',
      sortable: true,
      render: (val, row) => (
        <div className="flex items-center gap-3">
          {row.logoUrl ? (
            <img src={row.logoUrl} alt={val} className="h-8 w-8 object-cover border border-[#E5E5E5] rounded-full circle-avatar" />
          ) : (
            <div className="h-8 w-8 rounded-full bg-[#111111] text-white font-bold flex items-center justify-center text-xs font-mono circle-avatar">
              {row.logo}
            </div>
          )}
          <div>
            <div className="font-semibold text-[#111111]">{val}</div>
            <div className="text-[11px] text-[#6B7280]">ID: {row.id}</div>
          </div>
        </div>
      )
    },
    {
      key: 'owner',
      title: 'Owner',
      sortable: true,
    },
    {
      key: 'mobile',
      title: 'Contact',
      render: (val, row) => (
        <div>
          <div>{val}</div>
          <div className="text-[11px] text-[#6B7280]">{row.email}</div>
        </div>
      )
    },
    {
      key: 'status',
      title: 'Status',
      sortable: true,
      render: (val, row) => {
        const isSuspended = val === 'Suspended';
        return (
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            <div className="relative group flex items-center">
              <label className="relative inline-flex items-center cursor-pointer">
                <input
                  type="checkbox"
                  className="sr-only peer"
                  checked={!isSuspended}
                  onChange={() => {
                    setConfirmStatusChange({
                      isOpen: true,
                      businessId: row.id,
                      businessName: row.name,
                      isSuspended: isSuspended
                    });
                  }}
                />
                <div className="custom-toggle w-8 h-4 bg-[#D97706] rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[4px] after:bg-[#FEF3C7] after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-[#111111] peer-checked:after:bg-white transition-all"></div>
              </label>
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block bg-[#111111] text-white text-[10px] py-1 px-2 rounded whitespace-nowrap z-50 shadow-soft pointer-events-none">
                {isSuspended ? 'Suspended' : 'Active'}
              </div>
            </div>
            {/* <span className="text-[12px] font-medium text-[#111111]">
              {val}
            </span> */}
          </div>
        );
      }
    },
    {
      key: 'actions',
      title: 'Actions',
      render: (_, row) => (
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          <div className="relative group">
            <Button
              variant="secondary"
              size="sm"
              className="p-1.5"
              onClick={() => navigate(`/business-details/${row.id}`)}
            >
              <FiEye className="h-3.5 w-3.5 text-[#111111]" />
            </Button>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block bg-[#111111] text-white text-[10px] py-1 px-2 rounded whitespace-nowrap z-50 shadow-soft pointer-events-none">
              View Details
            </div>
          </div>

          <div className="relative group">
            <Button
              variant="secondary"
              size="sm"
              className="p-1.5"
              onClick={() => handleEditClick(row)}
            >
              <FiEdit className="h-3.5 w-3.5 text-[#4B5563]" />
            </Button>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block bg-[#111111] text-white text-[10px] py-1 px-2 rounded whitespace-nowrap z-50 shadow-soft pointer-events-none">
              Edit Details
            </div>
          </div>

          <div className="relative group">
            <Button
              variant="secondary"
              size="sm"
              className="p-1.5"
              onClick={() => setLogsModal({ isOpen: true, business: row })}
            >
              <FiClock className="h-3.5 w-3.5 text-[#4B5563]" />
            </Button>
            <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 hidden group-hover:block bg-[#111111] text-white text-[10px] py-1 px-2 rounded whitespace-nowrap z-50 shadow-soft pointer-events-none">
              View Activity Logs
            </div>
          </div>
        </div>
      )
    }
  ];

  const getTimelineEvents = (biz) => {
    if (!biz) return [];
    const events = [
      {
        title: "Store Registered",
        description: `Initial profile parameters configured. Contact: ${biz.mobile}`,
        by: biz.owner || "Super Admin",
        timestamp: `${biz.createdDate || '2025-05-15'} 10:30 AM`,
        type: 'create'
      },
      {
        title: "Business Details Updated",
        description: "General profile details and configuration settings modified.",
        by: "Super Admin",
        timestamp: `${biz.createdDate || '2025-05-15'} 11:45 AM`,
        type: 'edit'
      },
      {
        title: "Store Settings Configured",
        description: "Tax information, localization preference, and display preferences saved.",
        by: "System Settings",
        timestamp: `${biz.createdDate || '2025-05-15'} 12:15 PM`,
        type: 'settings'
      }
    ];

    if (biz.status === 'Active') {
      events.push({
        title: "Status Changed to Active",
        description: "Store access restored. Storefront is live online.",
        by: "Super Admin",
        timestamp: `${biz.createdDate || '2025-05-15'} 02:35 PM`,
        type: 'status_active'
      });
    } else if (biz.status === 'Suspended') {
      events.push({
        title: "Status Changed to Suspended",
        description: "Storefront access suspended by administration command.",
        by: "Super Admin",
        timestamp: "Yesterday, 04:15 PM",
        type: 'status_suspended'
      });
    }

    return events.reverse();
  };

  if (view === 'new' || view === 'edit') {
    const steps = newBiz.customerType === 'Individual'
      ? ['Business Info', 'Identity Details', 'Address Details', 'Modules']
      : ['Business Info', 'Identity Details', 'Address Details', 'Contact Persons', 'Modules'];

    const handleNext = (e) => {
      if (e) e.preventDefault();
      if (validateStep(currentStep)) {
        setCurrentStep(prev => Math.min(steps.length, prev + 1));
      }
    };

    const handlePrev = (e) => {
      if (e) e.preventDefault();
      setCurrentStep(prev => Math.max(1, prev - 1));
    };

    return (
      <div className="space-y-8">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">
              {view === 'edit' ? 'Edit Business Details' : 'Register Business'}
            </h1>
            <p className="text-[12px] text-[#6B7280]">
              {view === 'edit' ? 'Modify the configuration and parameters for this store.' : 'Configure and save the parameters for the new store.'}
            </p>
          </div>
          {/* <Button variant="secondary" icon={FiChevronLeft} onClick={() => navigate('/business-listing')}>
            Back
          </Button> */}
        </div>

        {/* Step Indicator */}
        <div className="bg-white border border-[#E5E5E5] rounded-custom p-6 shadow-soft mb-6">
          <div className="relative flex justify-between items-start max-w-3xl mx-auto">
            {/* The background line connecting all nodes */}
            <div className="absolute top-4 left-[56px] right-[56px] h-0.5 bg-[#E5E5E5] -translate-y-1/2 z-0" />

            {/* The active progress colored line */}
            <div
              className="absolute top-4 left-[56px] h-0.5 bg-[#111111] -translate-y-1/2 z-0 transition-all duration-300"
              style={{
                width: steps.length > 1 ? `calc((${currentStep - 1} / ${steps.length - 1}) * (100% - 112px))` : '0%'
              }}
            />

            {steps.map((stepName, index) => {
              const stepNumber = index + 1;
              const isActive = currentStep === stepNumber;
              const isCompleted = currentStep > stepNumber;
              const isPending = currentStep < stepNumber;

              return (
                <div key={stepName} className="flex flex-col items-center relative z-10 w-28 text-center">
                  {/* Circle Indicator */}
                  <div className="h-8 w-8 flex items-center justify-center mb-3">
                    {isCompleted && (
                      <div className="h-8 w-8 rounded-full bg-[#111111] text-white flex items-center justify-center shadow-sm">
                        <FiCheck className="h-4 w-4" />
                      </div>
                    )}
                    {isActive && (
                      <div className="h-8 w-8 rounded-full border-2 border-[#111111] bg-white flex items-center justify-center p-1 ring-4 ring-[#111111]/5">
                        <div className="h-3.5 w-3.5 rounded-full bg-[#111111]" />
                      </div>
                    )}
                    {isPending && (
                      <div className="h-8 w-8 rounded-full bg-[#E5E5E5] flex items-center justify-center" />
                    )}
                  </div>

                  {/* Texts */}
                  <div className="space-y-0.5">
                    <span className="text-[10px] font-bold tracking-wider text-[#9CA3AF] block uppercase">
                      Step {stepNumber}
                    </span>
                    <span className={`text-[12px] font-bold block leading-tight ${isActive ? 'text-[#111111]' : isCompleted ? 'text-[#4B5563]' : 'text-[#9CA3AF]'}`}>
                      {stepName}
                    </span>
                    <span className={`text-[10px] font-bold block ${isCompleted ? 'text-[#111111]' : isActive ? 'text-[#111111]' : 'text-[#9CA3AF]'}`}>
                      {isCompleted ? 'Completed' : isActive ? 'In Progress' : 'Pending'}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="bg-white border border-[#E5E5E5] rounded-custom p-6 shadow-soft">
          <form onSubmit={handleSubmit} className="space-y-6">

            {/* STEP 1: BUSINESS INFO */}
            {currentStep === 1 && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pb-6">
                {/* Customer Type */}
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-[#111111]">Customer Type</span>
                  <div className="flex items-center gap-4 text-sm py-1.5">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="customerType"
                        value="Business"
                        checked={newBiz.customerType === 'Business'}
                        onChange={e => setNewBiz({
                          ...newBiz,
                          customerType: 'Business',
                          gstTreatment: 'Registered Business - Composition'
                        })}
                        className="h-4 w-4 accent-black text-[#111111] focus:ring-[#111111]"
                      />
                      <span>Business</span>
                    </label>
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="radio"
                        name="customerType"
                        value="Individual"
                        checked={newBiz.customerType === 'Individual'}
                        onChange={e => {
                          const type = 'Individual';
                          setNewBiz({
                            ...newBiz,
                            customerType: type,
                            gstTreatment: 'Consumer',
                            name: '',
                            displayName: `${newBiz.firstName} ${newBiz.lastName}`.trim()
                          });
                        }}
                        className="h-4 w-4 accent-black text-[#111111] focus:ring-[#111111]"
                      />
                      <span>Individual</span>
                    </label>
                  </div>
                </div>

                {/* Primary Contact */}
                <div className="flex flex-col gap-1.5">
                  <span className={`text-xs font-semibold ${(!newBiz.firstName || !newBiz.lastName || formErrors.firstName || formErrors.lastName) ? 'text-red-600' : 'text-[#111111]'}`}>
                    Primary Contact <span className="text-red-600">*</span>
                  </span>
                  <div className="flex gap-2 w-full">
                    <select
                      value={newBiz.salutation}
                      onChange={e => setNewBiz({ ...newBiz, salutation: e.target.value })}
                      className="text-xs px-2 py-1.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111] w-20 shrink-0"
                    >
                      <option value="Mr.">Mr.</option>
                      <option value="Mrs.">Mrs.</option>
                      <option value="Ms.">Ms.</option>
                      <option value="Miss">Miss</option>
                      <option value="Dr.">Dr.</option>
                    </select>
                    <div className="flex flex-col w-full space-y-1">
                      <input
                        type="text"
                        placeholder="First Name"
                        value={newBiz.firstName}
                        onChange={e => {
                          const firstName = e.target.value.replace(/[0-9]/g, '');
                          const nextBiz = {
                            ...newBiz,
                            firstName,
                            displayName: newBiz.customerType === 'Individual' ? `${firstName} ${newBiz.lastName}`.trim() : newBiz.displayName
                          };
                          setNewBiz(nextBiz);

                          const nextErrs = { ...formErrors };
                          if (firstName.trim()) {
                            delete nextErrs.firstName;
                          } else {
                            nextErrs.firstName = "First Name is required.";
                          }
                          if (newBiz.customerType === 'Individual' && nextBiz.displayName.trim()) {
                            delete nextErrs.displayName;
                          }
                          setFormErrors(nextErrs);
                        }}
                        className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                      />
                      {formErrors.firstName && <p className="text-[10px] text-red-500 font-medium leading-none mt-1">{formErrors.firstName}</p>}
                    </div>
                    <div className="flex flex-col w-full space-y-1">
                      <input
                        type="text"
                        placeholder="Last Name"
                        value={newBiz.lastName}
                        onChange={e => {
                          const lastName = e.target.value.replace(/[0-9]/g, '');
                          const nextBiz = {
                            ...newBiz,
                            lastName,
                            displayName: newBiz.customerType === 'Individual' ? `${newBiz.firstName} ${lastName}`.trim() : newBiz.displayName
                          };
                          setNewBiz(nextBiz);

                          const nextErrs = { ...formErrors };
                          if (lastName.trim()) {
                            delete nextErrs.lastName;
                          } else {
                            nextErrs.lastName = "Last Name is required.";
                          }
                          if (newBiz.customerType === 'Individual' && nextBiz.displayName.trim()) {
                            delete nextErrs.displayName;
                          }
                          setFormErrors(nextErrs);
                        }}
                        className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                      />
                      {formErrors.lastName && <p className="text-[10px] text-red-500 font-medium leading-none mt-1">{formErrors.lastName}</p>}
                    </div>
                  </div>
                </div>

                {/* Company Name */}
                {newBiz.customerType !== 'Individual' ? (
                  <div className="flex flex-col gap-1.5">
                    <span className={`text-xs font-semibold ${!newBiz.name ? 'text-red-600' : 'text-[#111111]'}`}>
                      Company Name <span className="text-red-600">*</span>
                    </span>
                    <div className="w-full space-y-1">
                      <input
                        type="text"
                        placeholder="Company Name"
                        value={newBiz.name}
                        onChange={e => {
                          const name = e.target.value.replace(/[0-9]/g, '');
                          setNewBiz({ ...newBiz, name });
                          const nextErrs = { ...formErrors };
                          if (name.trim()) {
                            delete nextErrs.name;
                          }
                          setFormErrors(nextErrs);
                        }}
                        className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                      />
                      {formErrors.name && <p className="text-[10px] text-red-500 font-medium">{formErrors.name}</p>}
                    </div>
                  </div>
                ) : (
                  <div /> /* Empty placeholder to preserve grid positions */
                )}

                {/* Display Name */}
                <div className="flex flex-col gap-1.5">
                  <span className={`text-xs font-semibold ${!newBiz.displayName ? 'text-red-600' : 'text-[#111111]'}`}>
                    Display Name <span className="text-red-600">*</span>
                  </span>
                  <div className="w-full space-y-1">
                    <input
                      type="text"
                      placeholder="Display Name / Shop Name"
                      value={newBiz.displayName}
                      onChange={e => {
                        const displayName = e.target.value.replace(/[0-9]/g, '');
                        setNewBiz({ ...newBiz, displayName });
                        const nextErrs = { ...formErrors };
                        if (displayName.trim()) {
                          delete nextErrs.displayName;
                        }
                        setFormErrors(nextErrs);
                      }}
                      required
                      className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                    />
                    {formErrors.displayName && <p className="text-[10px] text-red-500 font-medium">{formErrors.displayName}</p>}
                  </div>
                </div>

                {/* Email Address */}
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-[#111111]">Email Address</span>
                  <div className="w-full space-y-1">
                    <input
                      type="email"
                      placeholder="owner@store.com"
                      value={newBiz.email}
                      onChange={e => {
                        const email = e.target.value;
                        setNewBiz({ ...newBiz, email });
                        const nextErrs = { ...formErrors };
                        if (!email || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                          delete nextErrs.email;
                        }
                        setFormErrors(nextErrs);
                      }}
                      className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                    />
                    {formErrors.email && <p className="text-[10px] text-red-500 font-medium">{formErrors.email}</p>}
                  </div>
                </div>

                {/* Phone */}
                <div className="flex flex-col gap-1.5">
                  <span className={`text-xs font-semibold ${(!newBiz.mobile && !newBiz.workPhone) ? 'text-red-600' : 'text-[#111111]'}`}>
                    Phone <span className="text-red-600">*</span> <span className="text-[10px] font-normal text-[#6B7280]">(At least one contact number is mandatory)</span>
                  </span>
                  <div className="w-full space-y-1">
                    <div className="grid grid-cols-2 gap-2 w-full">
                      <div className="flex border border-[#E5E5E5] rounded-custom overflow-hidden bg-white">
                        <select
                          value={newBiz.workPhoneCode}
                          onChange={e => setNewBiz({ ...newBiz, workPhoneCode: e.target.value })}
                          className="text-[10px] px-1.5 bg-gray-50 border-r border-[#E5E5E5] outline-none text-[#111111]"
                        >
                          <option value="+91">+91</option>
                          <option value="+1">+1</option>
                          <option value="+44">+44</option>
                        </select>
                        <input
                          type="text"
                          placeholder="Work Phone"
                          value={newBiz.workPhone}
                          onChange={e => {
                            const workPhone = e.target.value.replace(/\D/g, '').substring(0, 10);
                            setNewBiz({ ...newBiz, workPhone });
                            const nextErrs = { ...formErrors };
                            if (!workPhone || workPhone.length === 10) {
                              delete nextErrs.workPhone;
                            }
                            if (workPhone || newBiz.mobile) {
                              delete nextErrs.mobile;
                            }
                            setFormErrors(nextErrs);
                          }}
                          className="text-[11px] px-2 py-1 w-full outline-none"
                        />
                      </div>
                      <div className="flex border border-[#E5E5E5] rounded-custom overflow-hidden bg-white">
                        <select
                          value={newBiz.mobilePhoneCode}
                          onChange={e => setNewBiz({ ...newBiz, mobilePhoneCode: e.target.value })}
                          className="text-[10px] px-1.5 bg-gray-50 border-r border-[#E5E5E5] outline-none text-[#111111]"
                        >
                          <option value="+91">+91</option>
                          <option value="+1">+1</option>
                          <option value="+44">+44</option>
                        </select>
                        <input
                          type="text"
                          placeholder="Mobile"
                          value={newBiz.mobile}
                          onChange={e => {
                            const mobile = e.target.value.replace(/\D/g, '').substring(0, 10);
                            setNewBiz({ ...newBiz, mobile });
                            const nextErrs = { ...formErrors };
                            if (!mobile || mobile.length === 10) {
                              delete nextErrs.mobile;
                            }
                            if (mobile || newBiz.workPhone) {
                              delete nextErrs.mobile;
                            }
                            setFormErrors(nextErrs);
                          }}
                          className="text-[11px] px-2 py-1 w-full outline-none"
                        />
                      </div>
                    </div>
                    {(formErrors.mobile || formErrors.workPhone) && (
                      <p className="text-[10px] text-red-500 font-medium">{formErrors.mobile || formErrors.workPhone}</p>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* STEP 2: BUSINESS IDENTITY DETAILS */}
            {currentStep === 2 && (
              <div className="space-y-6 pb-6">
                <h3 className="text-xs font-bold text-[#111111] uppercase tracking-wider pb-2 border-b border-[#E5E5E5]">Business Identity Details</h3>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  {/* GST Treatment */}
                  {newBiz.customerType !== 'Individual' ? (
                    <div className="flex flex-col gap-1.5">
                      <span className={`text-xs font-semibold ${!newBiz.gstTreatment ? 'text-red-600' : 'text-[#111111]'}`}>
                        GST Treatment <span className="text-red-600">*</span>
                      </span>
                      <select
                        value={newBiz.gstTreatment}
                        onChange={e => setNewBiz({ ...newBiz, gstTreatment: e.target.value })}
                        className="text-xs px-2 py-1.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                      >
                        <option value="Registered Business - Composition">Registered Business - Composition</option>
                        <option value="Registered Business - Regular">Registered Business - Regular</option>
                        <option value="Unregistered Business">Unregistered Business</option>
                        <option value="Consumer">Consumer</option>
                      </select>
                    </div>
                  ) : (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-xs font-semibold text-[#6B7280]">GST Treatment</span>
                      <span className="text-xs font-semibold text-[#111111] bg-gray-50 border border-[#E5E5E5] px-3 py-1.5 rounded-custom">Consumer (Unregistered)</span>
                    </div>
                  )}

                  {/* GSTIN / UIN */}
                  {newBiz.customerType !== 'Individual' && newBiz.gstTreatment.startsWith('Registered') ? (
                    <div className="flex flex-col gap-1.5">
                      <span className={`text-xs font-semibold mt-0 ${(!newBiz.gst || formErrors.gst) ? 'text-red-600' : 'text-[#111111]'}`}>
                        GSTIN / UIN <span className="text-red-600">*</span>
                      </span>
                      <div className="space-y-1">
                        <input
                          type="text"
                          placeholder="27AAAAA1111A1Z1"
                          value={newBiz.gst}
                          onChange={e => {
                            const val = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').substring(0, 15);
                            setNewBiz({ ...newBiz, gst: val });
                            const nextErrs = { ...formErrors };
                            if (!val.trim()) {
                              nextErrs.gst = "GSTIN is required for registered business.";
                            } else if (!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(val)) {
                              nextErrs.gst = "Invalid GSTIN format (e.g. 27AAAAA1111A1Z1).";
                            } else {
                              delete nextErrs.gst;
                            }
                            setFormErrors(nextErrs);
                          }}
                          className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                        />
                        {(formErrors.gst || !newBiz.gst) && (
                          <p className="text-[10px] text-red-500 font-medium">
                            {formErrors.gst || "⚠️ GST Identification Number is mandatory for GST registered contact."}
                          </p>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div />
                  )}

                  {/* PAN Code */}
                  <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold text-[#111111]">PAN</span>
                    <div className="space-y-1">
                      <input
                        type="text"
                        placeholder="ABCDE1234F"
                        value={newBiz.pan}
                        onChange={e => setNewBiz({ ...newBiz, pan: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').substring(0, 10) })}
                        className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                      />
                      {formErrors.pan && <p className="text-[10px] text-red-500 font-medium">{formErrors.pan}</p>}
                    </div>
                  </div>

                  {/* Business Legal Name */}
                  {newBiz.customerType !== 'Individual' ? (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-xs font-semibold text-[#111111]">Business Legal Name</span>
                      <input
                        type="text"
                        placeholder="Legal Name (GST Records)"
                        value={newBiz.legalName}
                        onChange={e => setNewBiz({ ...newBiz, legalName: e.target.value })}
                        className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                      />
                    </div>
                  ) : (
                    <div />
                  )}

                  {/* Business Trade Name */}
                  {newBiz.customerType !== 'Individual' ? (
                    <div className="flex flex-col gap-1.5">
                      <span className="text-xs font-semibold text-[#111111]">Business Trade Name</span>
                      <input
                        type="text"
                        placeholder="Trade Name / Brand"
                        value={newBiz.tradeName}
                        onChange={e => setNewBiz({ ...newBiz, tradeName: e.target.value })}
                        className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                      />
                    </div>
                  ) : (
                    <div />
                  )}

                  {/* Account Status */}
                  <div className="flex flex-col gap-1.5">
                    <span className="text-xs font-semibold text-[#111111]">Account Status</span>
                    <div className="flex items-center gap-3 py-1.5">
                      <label className="relative inline-flex items-center cursor-pointer">
                        <input
                          type="checkbox"
                          className="sr-only peer"
                          checked={newBiz.status === 'Active'}
                          onChange={() => setNewBiz({
                            ...newBiz,
                            status: newBiz.status === 'Active' ? 'Suspended' : 'Active'
                          })}
                        />
                        <div className="custom-toggle w-8 h-4 bg-[#D97706] rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[4px] after:bg-[#FEF3C7] after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-[#111111] peer-checked:after:bg-white transition-all"></div>
                      </label>
                      <span className="text-xs font-semibold text-[#111111] min-w-[70px]">
                        {newBiz.status}
                      </span>
                    </div>
                  </div>

                  {/* Logo Upload with Crop Option */}
                  <div className="flex flex-col gap-1.5 md:col-span-3">
                    <span className="text-xs font-semibold text-[#111111]">Store Logo</span>
                    <div className="space-y-3">
                      {newBiz.logoUrl ? (
                        <div className="flex items-center gap-3">
                          <img
                            src={newBiz.logoUrl}
                            alt="Logo Preview"
                            className="h-16 w-16 object-cover border border-[#E5E5E5] bg-white rounded-custom"
                          />
                          <button
                            type="button"
                            onClick={() => setNewBiz({ ...newBiz, logoUrl: null })}
                            className="px-2.5 py-1 text-xs font-semibold text-[#DC2626] border border-[#DC2626] hover:bg-red-50 transition-colors"
                          >
                            ✕ Delete Logo
                          </button>
                        </div>
                      ) : isCropping ? (
                        <div className="border border-[#E5E5E5] bg-[#FAFAFA] p-3 space-y-3 rounded-custom max-w-md">
                          <p className="text-[11px] font-semibold text-[#111111]">Adjust / Crop store logo image</p>
                          <div className="relative h-40 bg-gray-200 flex items-center justify-center overflow-hidden border border-dashed border-[#C5C5C5]">
                            {tempLogoUrl && (
                              <img
                                src={tempLogoUrl}
                                alt="Raw Source"
                                className="max-h-full max-w-full opacity-80"
                                style={{ transform: 'scale(1.2)' }}
                              />
                            )}
                            <div className="absolute h-24 w-24 border-2 border-primary bg-transparent pointer-events-none flex items-center justify-center">
                              <span className="text-[9px] bg-black/60 text-white px-1">Crop Area</span>
                            </div>
                          </div>
                          <div className="flex justify-end gap-2">
                            <button
                              type="button"
                              onClick={() => {
                                setIsCropping(false);
                                setTempLogoUrl(null);
                              }}
                              className="px-2 py-1 text-xs text-[#6B7280] hover:text-[#111111]"
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setNewBiz({ ...newBiz, logoUrl: tempLogoUrl });
                                setIsCropping(false);
                                setTempLogoUrl(null);
                              }}
                              className="px-3 py-1 bg-[#111111] text-white text-xs hover:bg-black/90 font-semibold"
                            >
                              Crop & Save Logo
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div>
                          <input
                            type="file"
                            accept="image/*"
                            id="logo-upload-input"
                            className="hidden"
                            onChange={e => {
                              const file = e.target.files[0];
                              if (file) {
                                const reader = new FileReader();
                                reader.onloadend = () => {
                                  setTempLogoUrl(reader.result);
                                  setIsCropping(true);
                                };
                                reader.readAsDataURL(file);
                              }
                            }}
                          />
                          <label
                            htmlFor="logo-upload-input"
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-white border border-[#E5E5E5] hover:bg-[#F5F5F5] text-xs font-semibold text-[#111111] cursor-pointer transition-colors"
                          >
                            📷 Upload Logo Image
                          </label>
                          <p className="text-[10px] text-gray-400 mt-1">JPEG/PNG images only. Includes interactive crop controls.</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* STEP 3: STORE ADDRESS DETAILS */}
            {currentStep === 3 && (
              <div className="space-y-4 pb-6">
                <h3 className="text-xs font-bold text-[#111111] uppercase tracking-wider pb-2 border-b border-[#E5E5E5]">Store Address Details</h3>
                <div className="w-full">
                  <div className="space-y-4">
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                      {/* Street Address Row (Spans full width) */}
                      <div className="flex flex-col gap-1.5 md:col-span-4">
                        <span className={`text-[11px] font-semibold ${(!newBiz.billingStreet1 || !newBiz.billingStreet2) ? 'text-red-600' : 'text-[#6B7280]'}`}>
                          Street Address <span className="text-red-600">*</span>
                        </span>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <input
                            type="text"
                            placeholder="Street 1"
                            value={newBiz.billingStreet1}
                            onChange={e => setNewBiz({ ...newBiz, billingStreet1: e.target.value })}
                            className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                          />
                          <input
                            type="text"
                            placeholder="Street 2"
                            value={newBiz.billingStreet2}
                            onChange={e => setNewBiz({ ...newBiz, billingStreet2: e.target.value })}
                            className="text-xs px-3 py-1.5 w-full bg-white border border-[#E5E5E5] rounded-custom outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                          />
                        </div>
                      </div>

                      {/* Location Details Row (4 columns) */}
                      <div className="flex flex-col gap-1.5">
                        <span className={`text-[11px] font-semibold ${!newBiz.billingCountry ? 'text-red-600' : 'text-[#6B7280]'}`}>
                          Country/Region <span className="text-red-600">*</span>
                        </span>
                        <select
                          value={newBiz.billingCountry}
                          onChange={e => setNewBiz({ ...newBiz, billingCountry: e.target.value })}
                          className="text-xs px-3 py-1.5 bg-white border border-[#E5E5E5] rounded-custom outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                        >
                          <option value="India">India</option>
                          <option value="United States">United States</option>
                        </select>
                      </div>

                      <div className="flex flex-col gap-1.5">
                        <span className={`text-[11px] font-semibold ${!newBiz.billingState ? 'text-red-600' : 'text-[#6B7280]'}`}>
                          State <span className="text-red-600">*</span>
                        </span>
                        <select
                          value={newBiz.billingState}
                          onChange={e => setNewBiz({ ...newBiz, billingState: e.target.value })}
                          className="text-xs px-3 py-1.5 bg-white border border-[#E5E5E5] rounded-custom outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                        >
                          <option value="Maharashtra">Maharashtra</option>
                          <option value="Karnataka">Karnataka</option>
                          <option value="Delhi">Delhi</option>
                          <option value="Tamil Nadu">Tamil Nadu</option>
                        </select>
                      </div>

                      <div className="flex flex-col gap-1.5">
                        <span className={`text-[11px] font-semibold ${(formErrors.billingCity || !newBiz.billingCity) ? 'text-red-600' : 'text-[#6B7280]'}`}>
                          City <span className="text-red-600">*</span>
                        </span>
                        <div className="w-full space-y-1">
                          <input
                            type="text"
                            value={newBiz.billingCity}
                            onChange={e => {
                              const val = e.target.value.replace(/\d/g, '');
                              setNewBiz({ ...newBiz, billingCity: val });
                              const nextErrs = { ...formErrors };
                              if (val.trim()) {
                                delete nextErrs.billingCity;
                              } else {
                                nextErrs.billingCity = "City is required.";
                              }
                              setFormErrors(nextErrs);
                            }}
                            className={`text-xs px-3 py-1.5 w-full bg-white border ${formErrors.billingCity ? 'border-red-500' : 'border-[#E5E5E5]'} rounded-custom outline-none focus:ring-1 focus:ring-primary text-[#111111]`}
                          />
                          {formErrors.billingCity && <p className="text-[10px] text-red-500 font-medium">{formErrors.billingCity}</p>}
                        </div>
                      </div>

                      <div className="flex flex-col gap-1.5">
                        <span className={`text-[11px] font-semibold ${(formErrors.billingPinCode || !newBiz.billingPinCode) ? 'text-red-600' : 'text-[#6B7280]'}`}>
                          Pin Code <span className="text-red-600">*</span>
                        </span>
                        <div className="w-full space-y-1">
                          <input
                            type="text"
                            placeholder="6-digit Pincode"
                            value={newBiz.billingPinCode}
                            onChange={e => {
                              const val = e.target.value.replace(/\D/g, '').substring(0, 6);
                              setNewBiz({ ...newBiz, billingPinCode: val });
                              const nextErrs = { ...formErrors };
                              if (val.length === 6) {
                                delete nextErrs.billingPinCode;
                              } else {
                                nextErrs.billingPinCode = "Pin Code must be 6 digits.";
                              }
                              setFormErrors(nextErrs);
                            }}
                            className={`text-xs px-3 py-1.5 w-full bg-white border ${formErrors.billingPinCode ? 'border-red-500' : 'border-[#E5E5E5]'} rounded-custom outline-none focus:ring-1 focus:ring-primary text-[#111111]`}
                          />
                          {formErrors.billingPinCode && <p className="text-[10px] text-red-500 font-medium">{formErrors.billingPinCode}</p>}
                        </div>
                      </div>

                      {/* Phone Numbers Row (Up to 2 with Plus add button) */}
                      <div className="flex flex-col gap-1.5 md:col-span-4">
                        <span className={`text-[11px] font-semibold ${(!newBiz.billingPhones || !newBiz.billingPhones[0]) ? 'text-red-600' : 'text-[#6B7280]'}`}>
                          Phone Numbers <span className="text-red-600">*</span>
                        </span>
                        <div className="flex flex-wrap gap-3">
                          {(newBiz.billingPhones || ['']).map((phone, idx) => (
                            <div key={idx} className="flex items-center gap-2 w-full md:w-auto md:min-w-[280px]">
                              <div className="flex border border-[#E5E5E5] rounded-custom overflow-hidden bg-white w-full">
                                <select
                                  value={newBiz.billingPhoneCodes?.[idx] || '+91'}
                                  onChange={e => {
                                    const codes = [...(newBiz.billingPhoneCodes || ['+91'])];
                                    codes[idx] = e.target.value;
                                    setNewBiz({ ...newBiz, billingPhoneCodes: codes });
                                  }}
                                  className="text-[10px] px-1.5 bg-gray-50 border-r border-[#E5E5E5] outline-none text-[#111111]"
                                >
                                  <option value="+91">+91</option>
                                  <option value="+1">+1</option>
                                </select>
                                <input
                                  type="text"
                                  placeholder={`Phone ${idx + 1}`}
                                  value={phone}
                                  onChange={e => {
                                    const val = e.target.value.replace(/\D/g, '').substring(0, 10);
                                    const phones = [...(newBiz.billingPhones || [''])];
                                    phones[idx] = val;
                                    setNewBiz({
                                      ...newBiz,
                                      billingPhones: phones,
                                      billingPhone: phones[0] || '' // compatibility
                                    });
                                  }}
                                  className="text-xs px-2 py-1 w-full outline-none text-[#111111]"
                                />
                              </div>
                              {idx === 0 && (newBiz.billingPhones || ['']).length < 2 && (
                                <button
                                  type="button"
                                  onClick={() => setNewBiz({
                                    ...newBiz,
                                    billingPhones: [...(newBiz.billingPhones || ['']), ''],
                                    billingPhoneCodes: [...(newBiz.billingPhoneCodes || ['+91']), '+91']
                                  })}
                                  className="p-2 bg-white border border-[#E5E5E5] hover:bg-[#F5F5F5] rounded-custom text-[#111111] shrink-0"
                                >
                                  <FiPlus className="h-3.5 w-3.5" />
                                </button>
                              )}
                              {idx === 1 && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    const phones = [...(newBiz.billingPhones || [''])];
                                    phones.pop();
                                    const codes = [...(newBiz.billingPhoneCodes || ['+91'])];
                                    codes.pop();
                                    setNewBiz({
                                      ...newBiz,
                                      billingPhones: phones,
                                      billingPhoneCodes: codes,
                                      billingPhone: phones[0] || ''
                                    });
                                  }}
                                  className="p-2 bg-white border border-[#E5E5E5] hover:bg-red-50 text-red-600 rounded-custom shrink-0"
                                >
                                  <FiTrash2 className="h-3.5 w-3.5" />
                                </button>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* STEP 4: CONTACT PERSONS */}
            {currentStep === 4 && newBiz.customerType !== 'Individual' && (
              <div className="space-y-4 pb-6">
                <h3 className="text-xs font-bold text-[#111111] uppercase tracking-wider pb-2 border-b border-[#E5E5E5]">Contact Persons</h3>
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-[#E5E5E5] border border-[#E5E5E5] rounded-custom overflow-hidden">
                    <thead className="bg-[#FAFAFA]">
                      <tr>
                        <th scope="col" className="px-3 py-2 text-left text-[11px] font-bold text-[#6B7280] uppercase tracking-wider">Salutation</th>
                        <th scope="col" className="px-3 py-2 text-left text-[11px] font-bold text-[#6B7280] uppercase tracking-wider">First Name</th>
                        <th scope="col" className="px-3 py-2 text-left text-[11px] font-bold text-[#6B7280] uppercase tracking-wider">Last Name</th>
                        <th scope="col" className="px-3 py-2 text-left text-[11px] font-bold text-[#6B7280] uppercase tracking-wider">Email Address</th>
                        <th scope="col" className="px-3 py-2 text-left text-[11px] font-bold text-[#6B7280] uppercase tracking-wider">Mobile</th>
                        <th scope="col" className="relative px-3 py-2"></th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-[#E5E5E5] text-xs">
                      {newBiz.contactPersons.map((cp, idx) => (
                        <tr key={idx}>
                          <td className="px-2 py-1">
                            <select
                              value={cp.salutation}
                              onChange={e => {
                                const list = [...newBiz.contactPersons];
                                list[idx].salutation = e.target.value;
                                setNewBiz({ ...newBiz, contactPersons: list });
                              }}
                              className="text-xs px-1.5 py-1 bg-white border border-[#E5E5E5] rounded focus:outline-none"
                            >
                              <option value="Mr.">Mr.</option>
                              <option value="Mrs.">Mrs.</option>
                              <option value="Ms.">Ms.</option>
                            </select>
                          </td>
                          <td className="px-2 py-1">
                            <input
                              type="text"
                              value={cp.firstName}
                              onChange={e => {
                                const list = [...newBiz.contactPersons];
                                list[idx].firstName = e.target.value;
                                setNewBiz({ ...newBiz, contactPersons: list });
                              }}
                              className="text-xs px-2 py-1 border border-[#E5E5E5] rounded focus:outline-none w-24"
                            />
                          </td>
                          <td className="px-2 py-1">
                            <input
                              type="text"
                              value={cp.lastName}
                              onChange={e => {
                                const list = [...newBiz.contactPersons];
                                list[idx].lastName = e.target.value;
                                setNewBiz({ ...newBiz, contactPersons: list });
                              }}
                              className="text-xs px-2 py-1 border border-[#E5E5E5] rounded focus:outline-none w-24"
                            />
                          </td>
                          <td className="px-2 py-1">
                            <input
                              type="email"
                              value={cp.email}
                              onChange={e => {
                                const list = [...newBiz.contactPersons];
                                list[idx].email = e.target.value;
                                setNewBiz({ ...newBiz, contactPersons: list });
                              }}
                              className="text-xs px-2 py-1 border border-[#E5E5E5] rounded focus:outline-none w-40"
                            />
                          </td>
                          <td className="px-2 py-1">
                            <input
                              type="text"
                              value={cp.mobile}
                              onChange={e => {
                                const list = [...newBiz.contactPersons];
                                list[idx].mobile = e.target.value.replace(/\D/g, '').substring(0, 10);
                                setNewBiz({ ...newBiz, contactPersons: list });
                              }}
                              className="text-xs px-2 py-1 border border-[#E5E5E5] rounded focus:outline-none w-28"
                            />
                          </td>
                          <td className="px-2 py-1 text-right">
                            <button
                              type="button"
                              onClick={() => {
                                const list = newBiz.contactPersons.filter((_, i) => i !== idx);
                                setNewBiz({ ...newBiz, contactPersons: list });
                              }}
                              className="text-red-500 hover:text-red-700 font-medium inline-flex items-center justify-center p-1"
                            >
                              <FiTrash2 className="h-3.5 w-3.5" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <button
                  type="button"
                  disabled={
                    !newBiz.contactPersons.every(cp =>
                      cp.firstName.trim() !== '' &&
                      cp.lastName.trim() !== '' &&
                      (!cp.email || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cp.email)) &&
                      cp.mobile.replace(/\D/g, '').length === 10
                    )
                  }
                  onClick={() => {
                    setNewBiz({
                      ...newBiz,
                      contactPersons: [
                        ...newBiz.contactPersons,
                        { salutation: 'Mr.', firstName: '', lastName: '', email: '', mobile: '' }
                      ]
                    });
                  }}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 border text-xs font-semibold rounded-custom transition-all ${newBiz.contactPersons.every(cp =>
                    cp.firstName.trim() !== '' &&
                    cp.lastName.trim() !== '' &&
                    (!cp.email || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cp.email)) &&
                    cp.mobile.replace(/\D/g, '').length === 10
                  )
                    ? 'bg-[#FAFAFA] border-[#E5E5E5] hover:bg-[#F5F5F5] text-[#111111] cursor-pointer'
                    : 'bg-[#F3F4F6] border-[#E5E5E5] text-[#9CA3AF] cursor-not-allowed'
                    }`}
                >
                  <FiPlus className="h-3.5 w-3.5" />
                  Add Contact Person
                </button>
              </div>
            )}

            {/* STEP: MODULES CONFIGURATION */}
            {currentStep === (newBiz.customerType === 'Individual' ? 4 : 5) && (
              <div className="space-y-6 pb-6">
                <div>
                  <h3 className="text-xs font-bold text-[#111111] uppercase tracking-wider pb-2 border-b border-[#E5E5E5]">Module Configuration</h3>
                  <p className="text-[11px] text-[#6B7280] mt-1">Configure user modules and selection plans for this storefront.</p>
                </div>

                <div className="border border-[#E5E5E5] rounded-custom bg-white p-5 space-y-5">
                  <div className="flex items-start justify-between">
                    <div>
                      <h4 className="text-sm font-bold text-[#111111]">Bulk Message Module</h4>
                      <p className="text-xs text-[#6B7280] mt-0.5">Allows scheduling and broadcasting messages to segregated contact groups.</p>
                    </div>
                    <span className="text-[10px] font-bold text-white bg-[#111111] px-2.5 py-1 rounded-full uppercase tracking-wider">
                      Active
                    </span>
                  </div>

                  <div className="border-t border-[#E5E5E5] pt-4">
                    <span className="text-[11px] font-bold text-[#6B7280] uppercase tracking-wider block mb-3">Select Subscription Plan</span>
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                      {[
                        { id: 'free', name: 'Free Plan', desc: '250 messages per week', badge: 'Free' },
                        { id: 'basic', name: 'Basic Plan', desc: '1,000 messages per week', badge: 'Basic' },
                        { id: 'pro', name: 'Pro Plan', desc: '2,000 messages per week', badge: 'Pro' },
                        { id: 'premium', name: 'Premium Plan', desc: 'Unlimited messages', badge: 'Premium' },
                      ].map((plan) => {
                        const isSelected = newBiz.bulkMessagePlan === plan.id;
                        return (
                          <div
                            key={plan.id}
                            onClick={() => setNewBiz({ ...newBiz, bulkMessagePlan: plan.id })}
                            className={`border ${
                              isSelected ? 'bg-[#111111] border-[#111111]' : 'bg-white border-[#E5E5E5]'
                            } hover:border-[#111111] rounded-custom p-4 cursor-pointer transition-all flex flex-col justify-between relative`}
                          >
                            <div>
                              <div className="flex justify-between items-start gap-1">
                                <span className={`text-xs font-bold ${isSelected ? 'text-white' : 'text-[#111111]'}`}>{plan.name}</span>
                                {isSelected && <FiCheck className="h-3.5 w-3.5 text-white shrink-0" />}
                              </div>
                              <p className={`text-[11px] mt-1.5 leading-relaxed ${isSelected ? 'text-white/80' : 'text-[#6B7280]'}`}>{plan.desc}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Action buttons at the bottom of the page */}
            <div className="flex justify-center items-center border-t border-[#E5E5E5] mt-3 pt-3">
              <div className="flex justify-end gap-2 w-full max-w-3xl">
                {currentStep === 1 ? (
                  <>
                    <Button variant="secondary" icon={FiChevronLeft} onClick={() => {
                      if (view === 'edit') {
                        setEditingBizId(null);
                        resetForm();
                      } else {
                        navigate('/business-listing');
                      }
                    }}>
                      Cancel
                    </Button>
                    <Button variant="primary" onClick={handleNext} disabled={!isStepValid(currentStep)} className="flex items-center gap-1">
                      Next <FiChevronRight className="h-4 w-4" />
                    </Button>
                  </>
                ) : (
                  <>
                    <Button variant="secondary" icon={FiChevronLeft} onClick={handlePrev}>
                      Previous
                    </Button>
                    {currentStep < steps.length ? (
                      <Button variant="primary" onClick={handleNext} disabled={!isStepValid(currentStep)} className="flex items-center gap-1">
                        Next <FiChevronRight className="h-4 w-4" />
                      </Button>
                    ) : (
                      <Button variant="primary" onClick={handleSubmit} disabled={!isStepValid(currentStep)}>
                        Submit
                      </Button>
                    )}
                  </>
                )}
              </div>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">
            {isAgencyAdmin(currentRole) ? 'My Businesses' : 'Business Management'}
          </h1>
          <p className="text-[12px] text-[#6B7280]">
            {isAgencyAdmin(currentRole)
              ? 'Add, suspend, and manage the businesses under your agency.'
              : 'Add, suspend, audit, and configure tenant settings across all agencies.'}
          </p>
        </div>
        <div className="relative group">
          <Button variant="primary" icon={FiPlus} onClick={() => navigate('/business-register')} />
          <div className="absolute top-full right-0 mt-1.5 hidden group-hover:block bg-[#111111] text-white text-[10px] py-1 px-2 rounded whitespace-nowrap z-50 shadow-soft pointer-events-none">
            Register Business
          </div>
        </div>
      </div>

      {/* Stats Overview Section */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white border border-[#E5E5E5] rounded-custom p-4 shadow-soft flex flex-col justify-between">
          <div className="flex justify-between items-center gap-2">
            <span className="text-[10px] font-bold text-[#6B7280] tracking-wider uppercase">Total Businesses</span>
            <FiBriefcase className="h-3.5 w-3.5 text-[#6B7280]" />
          </div>
          <div className="text-2xl font-extrabold text-[#111111] mt-1.5">{businesses.length}</div>
        </div>
        <div className="bg-white border border-[#E5E5E5] rounded-custom p-4 shadow-soft flex flex-col justify-between">
          <div className="flex justify-between items-center gap-2">
            <span className="text-[10px] font-bold text-[#6B7280] tracking-wider uppercase">Active Businesses</span>
            <FiCheckCircle className="h-3.5 w-3.5 text-[#6B7280]" />
          </div>
          <div className="text-2xl font-extrabold text-[#111111] mt-1.5">{businesses.filter(b => b.status === 'Active').length}</div>
        </div>
        <div className="bg-white border border-[#E5E5E5] rounded-custom p-4 shadow-soft flex flex-col justify-between">
          <div className="flex justify-between items-center gap-2">
            <span className="text-[10px] font-bold text-[#6B7280] tracking-wider uppercase">Suspended Businesses</span>
            <FiAlertTriangle className="h-3.5 w-3.5 text-[#6B7280]" />
          </div>
          <div className="text-2xl font-extrabold text-[#111111] mt-1.5">{businesses.filter(b => b.status === 'Suspended').length}</div>
        </div>
        <div className="bg-white border border-[#E5E5E5] rounded-custom p-4 shadow-soft flex flex-col justify-between">
          <div className="flex justify-between items-center gap-2">
            <span className="text-[10px] font-bold text-[#6B7280] tracking-wider uppercase">Total Broadcasts Sent</span>
            <FiSend className="h-3.5 w-3.5 text-[#6B7280]" />
          </div>
          <div className="text-2xl font-extrabold text-[#111111] mt-1.5">142,504</div>
        </div>
      </div>

      <DataTable
        columns={columns}
        data={filteredData}
        searchKey="name"
        searchPlaceholder="Search businesses by name..."
        onRowClick={(row) => navigate(`/business-details/${row.id}`)}
        filterComponent={
          <div className="flex gap-2 text-xs font-semibold">
            {/* Agency multi-select (superadmin only) */}
            {isSuperAdmin(currentRole) && (
              <AgencyMultiSelect
                agencies={agencies}
                selectedIds={selectedAgencyIds}
                onChange={setSelectedAgencyIds}
              />
            )}

            {/* Status Filter */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-white border border-[#E5E5E5] px-3 py-2 rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
            >
              <option value="All">All Statuses</option>
              <option value="Active">Active</option>
              <option value="Suspended">Suspended</option>
            </select>
          </div>
        }
      />

      {/* Confirm Status Change Dialog */}
      <ConfirmDialog
        isOpen={confirmStatusChange.isOpen}
        onClose={() => setConfirmStatusChange({ ...confirmStatusChange, isOpen: false })}
        onConfirm={() => {
          suspendBusiness(confirmStatusChange.businessId);
          setConfirmStatusChange({ ...confirmStatusChange, isOpen: false });
        }}
        title={confirmStatusChange.isSuspended ? "Activate Store" : "Suspend Store"}
        message={
          <div className="flex flex-col items-center text-center space-y-3 py-2">
            {confirmStatusChange.isSuspended ? (
              <div className="h-12 w-12 rounded-full bg-emerald-50 border border-emerald-200 text-[#16A34A] flex items-center justify-center text-xl">
                🔓
              </div>
            ) : (
              <div className="h-12 w-12 rounded-full bg-red-50 border border-red-200 text-[#DC2626] flex items-center justify-center text-xl">
                ⚠️
              </div>
            )}
            <p className="text-[12px] text-[#4B5563] font-medium leading-relaxed px-2">
              {confirmStatusChange.isSuspended
                ? `Are you sure you want to activate the store "${confirmStatusChange.businessName}"? This will restore store access.`
                : `Are you sure you want to suspend the store "${confirmStatusChange.businessName}"? This will restrict user access.`}
            </p>
          </div>
        }
        confirmText={confirmStatusChange.isSuspended ? "Activate" : "Suspend"}
        cancelText="Cancel"
        variant={confirmStatusChange.isSuspended ? "primary" : "danger"}
      />

      {/* Activity Logs Timeline Modal */}
      <Modal
        isOpen={logsModal.isOpen}
        onClose={() => setLogsModal({ isOpen: false, business: null })}
        title={`Activity Logs: ${logsModal.business?.name || ''}`}
        size="md"
        footer={
          <Button variant="secondary" onClick={() => setLogsModal({ isOpen: false, business: null })}>
            Close
          </Button>
        }
      >
        <div className="space-y-6">
          <div className="flex justify-between items-center bg-[#FAFAFA] p-3 border border-[#E5E5E5] rounded-custom">
            <div>
              <span className="text-[10px] text-[#6B7280] block font-semibold tracking-wider">STORE IDENTIFIER</span>
              <span className="text-[12px] font-bold text-[#111111]">{logsModal.business?.id}</span>
            </div>
            <div className="text-right">
              <span className="text-[10px] text-[#6B7280] block font-semibold tracking-wider">CURRENT STATUS</span>
              <Badge variant={logsModal.business?.status === 'Active' ? 'success' : logsModal.business?.status === 'Suspended' ? 'danger' : 'warning'}>
                {logsModal.business?.status}
              </Badge>
            </div>
          </div>

          <div className="relative pl-6 border-l border-[#E5E5E5] space-y-6 ml-3">
            {getTimelineEvents(logsModal.business).map((event, idx) => {
              let markerBg = 'bg-gray-100 border-gray-300 text-gray-600';
              if (event.type === 'create') markerBg = 'bg-blue-50 border-blue-200 text-blue-600';
              if (event.type === 'edit') markerBg = 'bg-indigo-50 border-indigo-200 text-indigo-600';
              if (event.type === 'settings') markerBg = 'bg-teal-50 border-teal-200 text-teal-600';
              if (event.type === 'status_active') markerBg = 'bg-emerald-50 border-emerald-200 text-emerald-600';
              if (event.type === 'status_suspended') markerBg = 'bg-amber-50 border-amber-200 text-amber-600';

              return (
                <div key={idx} className="relative">
                  {/* Circle indicator */}
                  <span className={`absolute -left-[31px] top-0.5 flex items-center justify-center w-2.5 h-2.5 rounded-full border-2 ${markerBg}`}>
                  </span>

                  <div className="space-y-1">
                    <div className="flex justify-between items-start">
                      <h4 className="text-[12px] font-semibold text-[#111111]">{event.title}</h4>
                      <span className="text-[10px] text-[#6B7280]">{event.timestamp}</span>
                    </div>
                    <p className="text-[11px] text-[#4B5563]">{event.description}</p>
                    <div className="text-[9px] text-[#9CA3AF]">
                      Actioned by: <span className="font-semibold text-[#4B5563]">{event.by}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </Modal>


    </div>
  );
};
