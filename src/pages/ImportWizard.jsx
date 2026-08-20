import React, { useState } from 'react';
import { useApp } from '../context/AppContext';
import { Button, Card, Badge } from '../components/UI';
import { Upload, ArrowRight, ArrowLeft, Check, CheckCircle2, AlertCircle, RefreshCw } from 'lucide-react';

export const ImportWizard = () => {
  const { importContacts, setActivePath } = useApp();
  const [step, setStep] = useState(1);
  const [fileSelected, setFileSelected] = useState(null);
  const [progress, setProgress] = useState(0);

  // Mock data loaded from the file upload
  const rawExcelRows = [
    { name: "Rohit Sharma", phone: "9876543210", email: "rohit@gmail.com", location: "Mumbai", label: "VIP" },
    { name: "Virat Kohli", phone: "9812345678", email: "virat@yahoo.com", location: "Delhi", label: "VIP" },
    { name: "Jasprit Bumrah", phone: "9988776655", email: "jasprit@outlook.com", location: "Ahmedabad", label: "Loyal" },
    { name: "Hardik Pandya", phone: "9123456789", email: "", location: "Baroda", label: "Retailer" },
    { name: "Invalid Row", phone: "123", email: "bad-email", location: "", label: "" }, // Validation error row
  ];

  // Column Mapping State
  const [mappings, setMappings] = useState({
    name: 'name',
    mobile: 'phone',
    email: 'email',
    city: 'location',
    tags: 'label'
  });

  const handleFileSelect = () => {
    setFileSelected({ name: 'store_june_leads.xlsx', size: '24.5 KB' });
    setStep(2);
  };

  const handleMapColumns = () => {
    setStep(4);
  };

  const startImportSim = () => {
    setStep(5);
    let currentProgress = 0;
    const interval = setInterval(() => {
      currentProgress += 20;
      setProgress(currentProgress);
      if (currentProgress >= 100) {
        clearInterval(interval);
        // Do final import into global context (filtering out invalid row for success)
        const validImportedList = [
          { name: "Rohit Sharma", mobile: "+91 98765 43210", email: "rohit@gmail.com", city: "Mumbai", tags: ["VIP"] },
          { name: "Virat Kohli", mobile: "+91 98123 45678", email: "virat@yahoo.com", city: "Delhi", tags: ["VIP"] },
          { name: "Jasprit Bumrah", mobile: "+91 99887 76655", email: "jasprit@outlook.com", city: "Ahmedabad", tags: ["Loyal"] },
          { name: "Hardik Pandya", mobile: "+91 91234 56789", email: "", city: "Baroda", tags: ["Retailer"] }
        ];
        importContacts(validImportedList);
      }
    }, 400);
  };

  return (
    <div className="space-y-8">
      {/* Page Header */}
      <div>
        <h1 className="text-[18px] font-bold text-[#111111] tracking-tight">Import Contacts Wizard</h1>
        <p className="text-[12px] text-[#6B7280]">Process recipient sheets, resolve column fields, and run formatting validations.</p>
      </div>

      {/* Step Indicators bar */}
      <div className="flex items-center justify-between border-b border-[#E5E5E5] pb-5 text-xs font-semibold text-[#6B7280]">
        {[
          { num: 1, label: 'Upload Excel' },
          { num: 2, label: 'Preview Raw' },
          { num: 3, label: 'Map Columns' },
          { num: 4, label: 'Validate Fields' },
          { num: 5, label: 'Importing Status' }
        ].map(s => (
          <div key={s.num} className="flex items-center gap-2">
            <span className={`h-6 w-6 rounded-full flex items-center justify-center border font-bold ${step === s.num
              ? 'bg-[#111111] text-white border-[#111111]'
              : step > s.num
                ? 'bg-[#E8F5E9] text-[#16A34A] border-[#C8E6C9]'
                : 'bg-white border-[#E5E5E5]'
              }`}>
              {step > s.num ? <Check className="h-3.5 w-3.5" /> : s.num}
            </span>
            <span className={step === s.num ? 'text-[#111111]' : ''}>{s.label}</span>
            {s.num < 5 && <ArrowRight className="h-3.5 w-3.5 text-[#E5E5E5]" />}
          </div>
        ))}
      </div>

      {/* STEP 1: Upload File */}
      {step === 1 && (
        <Card className="max-w-2xl mx-auto py-12 flex flex-col items-center justify-center border-dashed border-2 border-[#E5E5E5] bg-[#FAFAFA] hover:bg-[#FAFAFA]/70 cursor-pointer transition-colors" onClick={handleFileSelect}>
          <div className="p-4 bg-white border border-[#E5E5E5] rounded-full shadow-soft mb-4">
            <Upload className="h-8 w-8 text-[#6B7280]" />
          </div>
          <h3 className="text-sm font-bold text-[#111111] mb-1">Click to upload spreadsheet</h3>
          <p className="text-xs text-[#6B7280] mb-6">Supports .xlsx, .xls, and .csv lists up to 20MB.</p>
          <Button variant="secondary" size="sm">Choose File</Button>
        </Card>
      )}

      {/* STEP 2: Preview Raw Data */}
      {step === 2 && (
        <div className="space-y-6">
          <Card title="Raw Sheet Preview" subtitle="Inspect records found in uploaded 'store_june_leads.xlsx'">
            <div className="overflow-x-auto border border-[#E5E5E5] rounded-custom">
              <table className="min-w-full text-left text-xs divide-y divide-[#E5E5E5]">
                <thead className="bg-[#FAFAFA] font-bold text-[#111111]">
                  <tr>
                    <th className="px-4 py-3">row</th>
                    {Object.keys(rawExcelRows[0]).map(key => (
                      <th key={key} className="px-4 py-3 capitalize">{key}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F5F5F5] font-medium text-[#6B7280]">
                  {rawExcelRows.map((row, idx) => (
                    <tr key={idx} className="hover:bg-[#FAFAFA]/40">
                      <td className="px-4 py-3 font-semibold text-[#111111]">{idx + 1}</td>
                      {Object.values(row).map((val, i) => (
                        <td key={i} className="px-4 py-3">{val || <span className="text-gray-300">-</span>}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-6 flex justify-between">
              <Button variant="secondary" icon={ArrowLeft} onClick={() => setStep(1)}>Back</Button>
              <Button variant="primary" icon={ArrowRight} onClick={() => setStep(3)}>Continue mapping</Button>
            </div>
          </Card>
        </div>
      )}

      {/* STEP 3: Map Columns */}
      {step === 3 && (
        <Card title="Column Header Mapping" subtitle="Bind spreadsheets headers to contact database fields">
          <div className="space-y-4 max-w-xl">
            {[
              { field: 'Contact Full Name', key: 'name', options: ['name', 'full_name', 'owner'] },
              { field: 'WhatsApp Mobile Number', key: 'mobile', options: ['phone', 'mobile', 'whatsapp'] },
              { field: 'Email Address', key: 'email', options: ['email', 'mail'] },
              { field: 'City', key: 'city', options: ['location', 'city', 'region'] },
              { field: 'Segment Tags', key: 'tags', options: ['label', 'tags', 'group'] }
            ].map(col => (
              <div key={col.key} className="grid grid-cols-2 gap-6 items-center text-xs border-b border-[#F5F5F5] pb-4">
                <span className="font-semibold text-[#111111]">{col.field}</span>
                <select
                  value={mappings[col.key]}
                  onChange={e => setMappings({ ...mappings, [col.key]: e.target.value })}
                  className="w-full text-xs px-3.5 py-2.5 bg-white border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-primary text-[#111111]"
                >
                  {col.options.map(opt => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              </div>
            ))}

            <div className="mt-8 flex justify-between">
              <Button variant="secondary" icon={ArrowLeft} onClick={() => setStep(2)}>Back</Button>
              <Button variant="primary" icon={ArrowRight} onClick={handleMapColumns}>Run validations</Button>
            </div>
          </div>
        </Card>
      )}

      {/* STEP 4: Validation */}
      {step === 4 && (
        <div className="space-y-6">
          <Card title="Database Validation Audit" subtitle="Errors and formats detected prior to importing">
            <div className="space-y-4">

              <div className="flex gap-6 text-xs text-[#6B7280]">
                <div className="flex items-center gap-1.5 p-3 bg-[#E8F5E9] border border-[#C8E6C9] rounded-custom flex-1">
                  <CheckCircle2 className="h-4 w-4 text-[#16A34A]" />
                  <span>4 Records Format Validated</span>
                </div>
                <div className="flex items-center gap-1.5 p-3 bg-[#FFEBEE] border border-[#FFCDD2] rounded-custom flex-1">
                  <AlertCircle className="h-4 w-4 text-[#DC2626]" />
                  <span>1 Formatting Error (Will be skipped)</span>
                </div>
              </div>

              {/* Validation errors table */}
              <div className="border border-[#E5E5E5] rounded-custom overflow-hidden text-xs">
                <div className="bg-[#FAFAFA] font-bold text-[#111111] px-4 py-3 border-b border-[#E5E5E5]">
                  Validation Summary Log
                </div>
                <div className="p-4 space-y-2 font-medium">
                  <p className="text-[#16A34A] flex items-center gap-2">✔ Row 1, 2, 3, 4: OK (Format Validated)</p>
                  <p className="text-[#DC2626] flex items-center gap-2">✘ Row 5: Mobile Number "123" is too short, Email "bad-email" is invalid</p>
                </div>
              </div>

              <div className="mt-8 flex justify-between">
                <Button variant="secondary" icon={ArrowLeft} onClick={() => setStep(3)}>Back</Button>
                <Button variant="primary" icon={Check} onClick={startImportSim}>Import verified records</Button>
              </div>

            </div>
          </Card>
        </div>
      )}

      {/* STEP 5: Progress Bar & Success */}
      {step === 5 && (
        <Card className="max-w-xl mx-auto py-10 flex flex-col items-center justify-center text-center">
          {progress < 100 ? (
            <div className="space-y-4 w-full px-8">
              <RefreshCw className="h-8 w-8 text-[#111111] animate-spin mx-auto" />
              <h3 className="text-sm font-bold text-[#111111]">Importing sheet rows...</h3>
              <div className="w-full bg-[#FAFAFA] border border-[#E5E5E5] h-3 rounded-full overflow-hidden">
                <div className="bg-[#111111] h-full rounded-full transition-all duration-300" style={{ width: `${progress}%` }} />
              </div>
              <span className="text-xs text-[#6B7280]">{progress}% Processed</span>
            </div>
          ) : (
            <div className="space-y-6">
              <div className="p-3 bg-[#E8F5E9] border border-[#C8E6C9] rounded-full inline-block text-[#16A34A] mb-2 animate-bounce">
                <Check className="h-8 w-8" />
              </div>
              <div className="space-y-2">
                <h3 className="text-md font-bold text-[#111111]">Successfully Imported Contacts!</h3>
                <p className="text-xs text-[#6B7280] max-w-sm">4 customer records mapped, validated, and appended to your active mailing list.</p>
              </div>
              <div className="flex gap-2 justify-center">
                <Button variant="secondary" onClick={() => setActivePath('contacts')}>View Database</Button>
                <Button variant="primary" onClick={() => setStep(1)}>Import Another Sheet</Button>
              </div>
            </div>
          )}
        </Card>
      )}

    </div>
  );
};
