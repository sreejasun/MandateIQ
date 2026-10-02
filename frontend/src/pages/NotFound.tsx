import { Link } from "react-router-dom";
import { EmptyState } from "../components/ui";

export default function NotFound() {
  return (
    <div className="panel">
      <EmptyState title="This page does not exist" action={<Link to="/cases" className="btn-primary">Go to cases</Link>}>
        The link may be out of date.
      </EmptyState>
    </div>
  );
}
