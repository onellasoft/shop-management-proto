import React, { useState, useRef, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';

/**
 * AgencyMultiSelect — a checkbox dropdown for filtering by one or more agencies.
 *
 * Props:
 *   agencies:    [{ id, name, ... }]
 *   selectedIds: string[]  — empty array means "All Agencies"
 *   onChange:    (ids: string[]) => void
 *
 * Selecting zero agencies (or clicking "All Agencies") clears the filter and
 * shows every business. Selecting one or more narrows to those agencies.
 */
export const AgencyMultiSelect = ({ agencies = [], selectedIds = [], onChange }) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef(null);

  // Close on outside click.
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const toggleAgency = (id) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };

  const selectAll = () => onChange([]);

  const allSelected = selectedIds.length === 0;

  // Trigger label: "All Agencies", the single agency name, or "N agencies".
  const label = allSelected
    ? 'All Agencies'
    : selectedIds.length === 1
      ? (agencies.find((a) => a.id === selectedIds[0])?.name ?? '1 agency')
      : `${selectedIds.length} agencies`;

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setIsOpen((v) => !v)}
        className="flex items-center gap-2 bg-white border border-[#E5E5E5] px-3 py-2 rounded-custom text-xs font-semibold text-[#111111] hover:bg-[#FAFAFA] focus:outline-none focus:ring-1 focus:ring-[#111111] transition-colors min-w-[9rem] justify-between"
      >
        <span className="truncate">{label}</span>
        <ChevronDown className={`h-3.5 w-3.5 text-[#6B7280] shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-1.5 w-60 bg-white border border-[#E5E5E5] rounded-custom shadow-premium z-40 overflow-hidden">
          {/* All Agencies option */}
          <button
            type="button"
            onClick={selectAll}
            className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-semibold text-[#111111] hover:bg-[#FAFAFA] border-b border-[#F5F5F5] text-left"
          >
            <span>All Agencies</span>
            {allSelected && <Check className="h-3.5 w-3.5 text-[#111111]" />}
          </button>

          {/* Individual agencies */}
          <div className="max-h-60 overflow-y-auto no-scrollbar">
            {agencies.length > 0 ? (
              agencies.map((agency) => {
                const checked = selectedIds.includes(agency.id);
                return (
                  <button
                    key={agency.id}
                    type="button"
                    onClick={() => toggleAgency(agency.id)}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs font-medium text-[#111111] hover:bg-[#FAFAFA] text-left"
                  >
                    <span
                      className={`h-4 w-4 shrink-0 rounded border flex items-center justify-center transition-colors ${
                        checked ? 'bg-[#111111] border-[#111111]' : 'bg-white border-[#D1D5DB]'
                      }`}
                    >
                      {checked && <Check className="h-3 w-3 text-white" />}
                    </span>
                    <span className="truncate">{agency.name}</span>
                  </button>
                );
              })
            ) : (
              <div className="px-3 py-4 text-center text-xs text-[#6B7280]">No agencies</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
