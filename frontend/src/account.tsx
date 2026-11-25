import { useEffect, useState } from "react";
import { z } from "zod";

// oauth2-proxy answers these in front of the app. Local runs have no login, so none exist.
const USERINFO = "/oauth2/userinfo";

export function signOutUrl(back: string): string {
  return `/oauth2/sign_out?rd=${encodeURIComponent(back)}`;
}

/** The signed-in email, or null wherever nothing signs people in. */
export function useAccount(): string | null {
  const [email, setEmail] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    // Without the proxy the path falls through to the page itself, which is not JSON.
    fetch(USERINFO, { headers: { Accept: "application/json" } })
      .then((response) => (response.ok ? response.json() : null))
      .then((body: unknown) => {
        const info = z.object({ email: z.string().min(1) }).safeParse(body);
        if (live && info.success) setEmail(info.data.email);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);
  return email;
}

export function AccountMenu({ email }: { email: string }) {
  return (
    <span className="account">
      <span className="account-email">
        <span className="sr-only">로그인한 계정 </span>
        {email}
      </span>
      <a className="button quiet" href={signOutUrl("/")}>
        로그아웃
      </a>
    </span>
  );
}

export function MissingJourney({
  email,
  link,
  onNew,
}: {
  email: string | null;
  link: string;
  onNew: () => void;
}) {
  return (
    <section className="missing-journey" aria-labelledby="missing-journey">
      <h2 id="missing-journey">이 링크의 여정을 열 수 없어요</h2>
      <p>
        주소가 틀렸거나, 다른 Google 계정으로 만든 여정일 수 있어요. 여정은 만든
        계정으로 로그인해야 열려요.
      </p>
      {email && (
        <p>
          지금 로그인한 계정: <strong>{email}</strong>
        </p>
      )}
      <div className="missing-actions">
        <button onClick={onNew}>새 여정 시작하기</button>
        {email && (
          <a className="button" href={signOutUrl(link)}>
            다른 계정으로 로그인
          </a>
        )}
      </div>
    </section>
  );
}
