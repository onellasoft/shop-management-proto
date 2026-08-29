import React, { useState, useMemo } from 'react';
import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Search as SearchIcon } from 'lucide-react';
import { Button } from './UI';

export const DataTable = ({
  columns,
  data = [],
  searchPlaceholder = "Search list...",
  searchKey = "",
  filterComponent,
  emptyState,
  onRowClick,
  actions
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [rowsPerPage, setRowsPerPage] = useState(10);
  const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });

  // Handle Sort
  const requestSort = (key) => {
    let direction = 'asc';
    if (sortConfig.key === key && sortConfig.direction === 'asc') {
      direction = 'desc';
    }
    setSortConfig({ key, direction });
  };

  // Filter & Search & Sort Data
  const processedData = useMemo(() => {
    let result = [...data];

    // Search filter
    if (searchQuery && searchKey) {
      result = result.filter(item => {
        const value = item[searchKey];
        if (!value) return false;
        return value.toString().toLowerCase().includes(searchQuery.toLowerCase());
      });
    } else if (searchQuery) {
      // Global search across all fields if no specific key is provided
      result = result.filter(item => {
        return Object.values(item).some(val =>
          val && val.toString().toLowerCase().includes(searchQuery.toLowerCase())
        );
      });
    }

    // Sort
    if (sortConfig.key) {
      result.sort((a, b) => {
        let aVal = a[sortConfig.key];
        let bVal = b[sortConfig.key];

        if (typeof aVal === 'string') {
          return sortConfig.direction === 'asc'
            ? aVal.localeCompare(bVal)
            : bVal.localeCompare(aVal);
        }

        if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
        if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
        return 0;
      });
    }

    return result;
  }, [data, searchQuery, searchKey, sortConfig]);

  // Pagination calculations
  const totalPages = Math.ceil(processedData.length / rowsPerPage) || 1;
  const startIndex = (currentPage - 1) * rowsPerPage;
  const paginatedData = useMemo(() => {
    return processedData.slice(startIndex, startIndex + rowsPerPage);
  }, [processedData, startIndex, rowsPerPage]);

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && newPage <= totalPages) {
      setCurrentPage(newPage);
    }
  };

  return (
    <div className="space-y-4">
      {/* Search & Filter Header */}
      <div className="flex flex-col sm:flex-row gap-3 items-center justify-between">
        <div className="relative w-full sm:max-w-xs">
          <SearchIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-[#6B7280]" />
          <input
            type="text"
            className="w-full text-sm pl-9 pr-4 py-2 border border-[#E5E5E5] rounded-custom focus:outline-none focus:ring-1 focus:ring-[#111111] focus:border-[#111111]"
            placeholder={searchPlaceholder}
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setCurrentPage(1);
            }}
          />
        </div>

        <div className="flex gap-2 w-full sm:w-auto items-center justify-end">
          {filterComponent}
          {actions}
        </div>
      </div>

      {/* Table Container */}
      <div className="overflow-x-auto border border-[#E5E5E5] rounded-custom bg-white">
        <table className="min-w-full divide-y divide-[#E5E5E5] text-left text-sm">
          <thead className="bg-[#FAFAFA]">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  scope="col"
                  className={`px-6 py-4 font-semibold text-[#111111] select-none ${col.sortable ? 'cursor-pointer hover:bg-[#F5F5F5]' : ''} ${col.className || ''}`}
                  onClick={() => col.sortable && requestSort(col.key)}
                >
                  <div className="flex items-center gap-1.5">
                    {col.title}
                    {col.sortable && sortConfig.key === col.key && (
                      sortConfig.direction === 'asc' ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>

          <tbody className="divide-y divide-[#E5E5E5] bg-white">
            {paginatedData.length > 0 ? (
              paginatedData.map((row, idx) => (
                <tr
                  key={row.id || idx}
                  className={`hover:bg-[#FAFAFA]/70 transition-colors duration-150 ${onRowClick ? 'cursor-pointer' : ''}`}
                  onClick={() => onRowClick && onRowClick(row)}
                >
                  {columns.map((col) => (
                    <td key={col.key} className={`px-6 py-4 text-[#111111] whitespace-nowrap ${col.className || ''}`}>
                      {col.render ? col.render(row[col.key], row) : row[col.key]}
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={columns.length} className="px-6 py-12 text-center text-[#6B7280]">
                  {emptyState || "No records match your search query."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      {processedData.length > 0 && (
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 py-1 text-[12px] text-[#6B7280]">
          <div>
            Showing <span className="font-medium text-[#111111]">{startIndex + 1}</span> to{' '}
            <span className="font-medium text-[#111111]">
              {Math.min(startIndex + rowsPerPage, processedData.length)}
            </span>{' '}
            of <span className="font-medium text-[#111111]">{processedData.length}</span> entries
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1">
              <span className="text-[12px]">Rows:</span>
              <select
                className="bg-white border border-[#E5E5E5] rounded-md px-1.5 py-1 text-[12px] text-[#111111] focus:outline-none"
                value={rowsPerPage}
                onChange={(e) => {
                  setRowsPerPage(Number(e.target.value));
                  setCurrentPage(1);
                }}
              >
                {[5, 10, 20, 50].map((num) => (
                  <option key={num} value={num}>
                    {num}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center gap-1">
              <Button
                variant="secondary"
                size="sm"
                className="px-2"
                onClick={() => handlePageChange(currentPage - 1)}
                disabled={currentPage === 1}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="text-xs px-2 text-[#111111] font-medium">
                Page {currentPage} of {totalPages}
              </span>
              <Button
                variant="secondary"
                size="sm"
                className="px-2"
                onClick={() => handlePageChange(currentPage + 1)}
                disabled={currentPage === totalPages}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
