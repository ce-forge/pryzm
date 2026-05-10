import React from "react";

interface ConfirmModalProps {
  isOpen: boolean;
  title: string;
  description: string;
  confirmText?: string;
  cancelText?: string;
  onConfirm: () => void;
  onCancel: () => void;
  danger?: boolean;
}

export default function ConfirmModal({
  isOpen, 
  title, 
  description, 
  confirmText = "Delete", 
  cancelText = "Cancel", 
  onConfirm, 
  onCancel, 
  danger = true
}: ConfirmModalProps) {
  if (!isOpen) return null;

  return (
    <div 
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm" 
      onClick={onCancel}
    >
      <div 
        className="bg-[#1e1f20] p-6 rounded-2xl border border-[#333537] shadow-2xl max-w-sm w-full mx-4" 
        onClick={e => e.stopPropagation()}
      >
        <h3 className="text-lg font-bold text-white mb-2">{title}</h3>
        <p className="text-sm text-gray-400 mb-6">{description}</p>
        <div className="flex justify-end gap-3">
          <button 
            onClick={onCancel} 
            className="px-4 py-2 text-gray-400 hover:text-white transition-colors"
          >
            {cancelText}
          </button>
          <button 
            onClick={onConfirm} 
            className={`px-5 py-2 font-bold rounded-xl transition-all ${
                danger ? 'bg-red-600 hover:bg-red-500 text-white' : 'bg-blue-600 hover:bg-blue-500 text-white'
            }`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}