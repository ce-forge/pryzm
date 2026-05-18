export default function AdminAuditPage() {
  return (
    <div className="max-w-3xl">
      <h2 className="text-xl font-semibold mb-2">Audit</h2>
      <p className="text-sm text-gray-400">
        Paginated audit log with filters by user, event type, workspace, and
        time range. Click a row for full payload + linked entities.
        Backend endpoints (F.3) shipped; UI lands in D.5.
      </p>
    </div>
  );
}
