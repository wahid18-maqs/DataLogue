// Reusable loading spinner shown while data is being fetched or processed.

export default function Loading({ label = "Loading..." }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10 text-slate-500">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-indigo-600" />
      <p className="text-sm font-medium">{label}</p>
    </div>
  );
}
