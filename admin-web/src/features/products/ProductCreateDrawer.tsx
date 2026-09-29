import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";

import { useCreateProduct, type AddOn, type Variant } from "@/api/catalog";
import { loadCategoryOptions } from "@/api/pickers";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Card";
import { InlineError } from "@/components/ui/Feedback";
import { Checkbox, Field, Input, TextArea } from "@/components/ui/Field";
import { FileDrop, Picker } from "@/components/ui/Inputs";
import { Drawer } from "@/components/ui/Overlay";
import { useToast } from "@/components/ui/Toast";
import { pct } from "@/lib/format";
import { ACCEPT } from "@/lib/upload";

import { AddOnsEditor, VariantsEditor, cleanOptions, rateFromPercent } from "./ProductEditors";

/** Add Product on a vendor's behalf (Vendor Details → Products). */
export function ProductCreateDrawer({
  vendor,
  open,
  onClose,
}: {
  vendor: { id: string; name: string; commission_rate: number };
  open: boolean;
  onClose: () => void;
}) {
  const create = useCreateProduct();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const [price, setPrice] = useState("");
  const [commission, setCommission] = useState("");
  const [category, setCategory] = useState<{ id: string; name: string } | null>(null);
  const [featured, setFeatured] = useState(false);
  const [veg, setVeg] = useState(false);
  const [variants, setVariants] = useState<Variant[]>([]);
  const [addOns, setAddOns] = useState<AddOn[]>([]);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setDescription("");
    setImage(null);
    setPrice("");
    setCommission("");
    setCategory(null);
    setFeatured(false);
    setVeg(false);
    setVariants([]);
    setAddOns([]);
    setError(null);
  }, [open]);

  const submit = async () => {
    setError(null);
    try {
      const base = Number(price);
      if (!name.trim()) throw new Error("The product needs a name.");
      if (!category) throw new Error("Choose the category it is listed under.");
      if (!price.trim() || !Number.isFinite(base) || base < 0) throw new Error("Enter a valid price.");
      await create.mutateAsync({
        vendorId: vendor.id,
        body: {
          name: name.trim(),
          description: description.trim() || null,
          image_url: image,
          base_price: base,
          platform_category_id: category.id,
          commission_rate: rateFromPercent(commission),
          is_featured: featured,
          is_veg: veg,
          variants: cleanOptions(variants, "variant"),
          add_ons: cleanOptions(addOns, "add-on"),
        },
      });
      toast(`${name.trim()} added to ${vendor.name}'s menu`);
      onClose();
    } catch (e) {
      setError(e);
    }
  };

  return (
    <Drawer
      open={open}
      onClose={onClose}
      eyebrow={vendor.name}
      title="Add product"
      footer={
        <div className="flex gap-3">
          <Button variant="outline" onClick={onClose} className="flex-1">
            Cancel
          </Button>
          <Button onClick={submit} loading={create.isPending} icon={<CheckCircle2 className="size-4" />} className="flex-1">
            Add product
          </Button>
        </div>
      }
    >
      <Panel title="Basic">
        <div className="space-y-3">
          <FileDrop value={image} onChange={setImage} accept={ACCEPT.image} label="Add product image" />
          <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} maxLength={180} autoFocus />}</Field>
          <Field label="Description">
            {(id) => <TextArea id={id} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} className="min-h-20" />}
          </Field>
          <Field
            label="Category"
            hint="The product goes into the vendor's menu section for this category; one is created if they have none."
          >
            {() => (
              <Picker
                value={category?.id ?? null}
                valueLabel={category?.name}
                onChange={(o) => setCategory(o && { id: o.value, name: o.label })}
                load={loadCategoryOptions}
                placeholder="Choose a category"
                searchPlaceholder="Search categories…"
              />
            )}
          </Field>
          <div className="flex flex-wrap gap-5 pt-1">
            <Checkbox checked={featured} onChange={setFeatured} label="Featured" />
            <Checkbox checked={veg} onChange={setVeg} label="Vegetarian" />
          </div>
        </div>
      </Panel>
      <Panel title="Pricing">
        <div className="space-y-3">
          <Field label="Price (৳)">{(id) => <Input id={id} type="number" min={0} value={price} onChange={(e) => setPrice(e.target.value)} />}</Field>
          <Field label="Commission (%)" hint={`Leave empty to use the category's rate, or the vendor's ${pct(vendor.commission_rate)}.`}>
            {(id) => (
              <Input id={id} type="number" min={0} max={100} step="0.5" value={commission} onChange={(e) => setCommission(e.target.value)} />
            )}
          </Field>
        </div>
      </Panel>
      <Panel title="Variants">
        <VariantsEditor value={variants} onChange={setVariants} />
      </Panel>
      <Panel title="Addons">
        <AddOnsEditor value={addOns} onChange={setAddOns} />
      </Panel>
      <InlineError error={error} />
    </Drawer>
  );
}
