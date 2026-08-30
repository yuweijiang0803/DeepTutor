/** Normalize a version string into a ``vMAJOR.MINOR.PATCH`` tag form.
 *
 * Accepts PEP 440 / semver forms used in ``deeptutor/__version__.py`` and
 * GitHub release tags (``1.4.0``, ``v1.4.0``, ``1.4.0rc1``, ``v1.0.0-beta.4``),
 * plus 4-segment patch tags used for custom desktop releases on top of an
 * upstream version (``1.6.0.1``, ``1.6.0.2``).
 * Rejects git-describe output like ``v1.2.3-5-gabc1234``.
 */
export function normalizeVersionTag(
  raw: string | null | undefined,
): string | null {
  const value = raw?.trim();
  if (!value) return null;
  const match = value.match(
    /^v?(\d+\.\d+\.\d+(?:\.\d+)?(?:(?:rc|a|b)\d+|\.dev\d+|\.post\d+|-[A-Za-z][0-9A-Za-z.-]*)?)$/,
  );
  return match ? `v${match[1]}` : null;
}
